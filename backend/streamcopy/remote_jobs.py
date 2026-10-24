from __future__ import annotations

import hashlib
import queue
import threading
from pathlib import Path, PurePosixPath
from typing import Any

from backend.core.logging_setup import log_error, log_event, log_warning
from backend.remote.service import RemoteConnectionError, RemoteNotFound
from backend.streamcopy import endpoints, journal


def _jobs():
    # Lazy import keeps the stable local engine free from an import cycle.
    import backend.streamcopy.jobs as jobs

    return jobs


def _endpoint_states(job: dict[str, Any], *, connect_remote: bool = True) -> list[dict[str, Any]]:
    result = []
    for role, endpoint in (
        ("source", dict(job.get("source_endpoint") or {})),
        ("destination", dict(job.get("destination_endpoint") or {})),
    ):
        state = endpoints.state(endpoint, connect_remote=connect_remote)
        result.append({"role": role, **state})
    return result


def _wait_for_endpoints(
    job_id: str,
    cancel: threading.Event,
    lease_lost: threading.Event,
) -> None:
    jobs = _jobs()
    was_waiting = False
    while True:
        jobs._control_check(cancel, lease_lost)
        job = jobs._load_job(job_id)
        states = _endpoint_states(job)
        unavailable = [item for item in states if not item.get("available")]
        if not unavailable:
            if was_waiting or job.get("status") == "waiting_endpoint":
                jobs._persist_job(
                    job_id,
                    status="recovering",
                    waiting_since=None,
                    auto_resumes=int(job.get("auto_resumes") or 0) + 1,
                    error=None,
                )
                log_event("streamcopy.remote_endpoint_resumed", job_id=job_id)
            return

        if not was_waiting and job.get("status") != "waiting_endpoint":
            jobs._persist_job(
                job_id,
                status="waiting_endpoint",
                waiting_since=jobs._now(),
                wait_cycles=int(job.get("wait_cycles") or 0) + 1,
                error="; ".join(
                    f"{item['role']}:{item.get('reason')}" for item in unavailable
                ),
            )
            log_warning(
                "streamcopy.remote_endpoint_waiting",
                job_id=job_id,
                reason=";".join(
                    f"{item['role']}:{item.get('reason')}" for item in unavailable
                ),
            )
        was_waiting = True
        if cancel.wait(jobs.ENDPOINT_RECHECK_SECONDS):
            jobs._control_check(cancel, lease_lost)


def _source_stat_matches(
    source_endpoint: dict[str, Any],
    item: dict[str, Any],
) -> bool:
    try:
        current = endpoints.stat(source_endpoint, str(item["source_path"]))
    except (OSError, FileNotFoundError, RemoteNotFound, RemoteConnectionError, KeyError):
        return False
    if bool(current["is_dir"]) or int(current["size"]) != int(item["size"]):
        return False
    expected_mtime = item.get("source_mtime_ns")
    actual_mtime = current.get("modified_ns")
    return (
        expected_mtime is None
        or actual_mtime is None
        or int(expected_mtime) == int(actual_mtime)
    )


def _hash_range(
    endpoint: dict[str, Any],
    path: str,
    start: int,
    size: int,
) -> str:
    digest = hashlib.sha256()
    remaining = int(size)
    with endpoints.open_read(endpoint, path, offset=int(start)) as stream:
        while remaining > 0:
            data = stream.read(min(8 * 1024 * 1024, remaining))
            if not data:
                raise OSError(f"Unexpected EOF while hashing {path}")
            digest.update(data)
            remaining -= len(data)
    return digest.hexdigest()


def _hash_file(endpoint: dict[str, Any], path: str) -> str:
    digest = hashlib.sha256()
    with endpoints.open_read(endpoint, path) as stream:
        while True:
            data = stream.read(8 * 1024 * 1024)
            if not data:
                return digest.hexdigest()
            digest.update(data)


def _verify_pair(
    source_endpoint: dict[str, Any],
    source_path: str,
    destination_endpoint: dict[str, Any],
    target_path: str,
    mode: str,
) -> None:
    source = endpoints.stat(source_endpoint, source_path)
    target = endpoints.stat(destination_endpoint, target_path)
    if int(source["size"]) != int(target["size"]):
        raise OSError(
            f"Size verification failed: source={source['size']}, target={target['size']}"
        )
    if mode == "sha256":
        if _hash_file(source_endpoint, source_path) != _hash_file(
            destination_endpoint, target_path
        ):
            raise OSError(f"SHA-256 verification failed: {target_path}")


def _relative_join(relative_root: str, name: str) -> str:
    if not relative_root:
        return name
    return str(PurePosixPath(relative_root) / name)


def _build_manifest(job_id: str) -> None:
    jobs = _jobs()
    job = jobs._load_job(job_id)
    source_endpoint = dict(job["source_endpoint"])
    destination_endpoint = dict(job["destination_endpoint"])
    source_path = str(job["source_path"])
    destination_root = str(job["destination_path"])

    source_info = endpoints.stat(source_endpoint, source_path)
    if source_info.get("is_symlink"):
        raise ValueError("source root cannot be a symlink")

    endpoints.makedirs(destination_endpoint, destination_root)
    destination_info = endpoints.stat(destination_endpoint, destination_root)
    if not destination_info["is_dir"]:
        raise NotADirectoryError(destination_root)

    source_name = endpoints.basename(source_endpoint, source_path)
    if not source_info["is_dir"]:
        target_root = destination_root
        target = endpoints.join(destination_endpoint, destination_root, source_name)
        items = [
            {
                "item_index": 0,
                "source_path": source_path,
                "target_path": target,
                "partial_path": f"{target}.dspart-{job_id[:12]}",
                "size": int(source_info["size"]),
                "source_mtime_ns": source_info.get("modified_ns"),
            }
        ]
        directory_count = 0
    else:
        target_root = endpoints.join(destination_endpoint, destination_root, source_name)
        items: list[dict[str, Any]] = []
        directories: set[str] = {target_root}
        stack: list[tuple[str, str]] = [(source_path, "")]

        while stack:
            current_path, relative_root = stack.pop()
            for entry in endpoints.listdir(source_endpoint, current_path):
                relative = _relative_join(relative_root, str(entry["name"]))
                if entry.get("is_symlink"):
                    jobs._append_warning(
                        job_id,
                        str(entry["path"]),
                        "remote/local link skipped during manifest",
                    )
                    continue
                if entry["is_dir"]:
                    target_dir = endpoints.join(destination_endpoint, target_root, relative)
                    directories.add(target_dir)
                    stack.append((str(entry["path"]), relative))
                    continue

                target = endpoints.join(destination_endpoint, target_root, relative)
                items.append(
                    {
                        "item_index": len(items),
                        "source_path": str(entry["path"]),
                        "target_path": target,
                        "partial_path": f"{target}.dspart-{job_id[:12]}",
                        "size": int(entry["size"]),
                        "source_mtime_ns": entry.get("modified_ns"),
                    }
                )

        directory_count = len(directories)
        for directory in sorted(
            directories,
            key=lambda value: value.count("/") if destination_endpoint["kind"] == "remote"
            else len(Path(value).parts),
        ):
            endpoints.makedirs(destination_endpoint, directory)

    journal.replace_manifest(
        job_id,
        target_root=str(target_root),
        items=items,
        directory_count=directory_count,
    )
    jobs._load_job(job_id)


def _safe_resume_offset(
    job_id: str,
    item: dict[str, Any],
    source_endpoint: dict[str, Any],
    destination_endpoint: dict[str, Any],
    cancel: threading.Event,
    lease_lost: threading.Event,
) -> int:
    jobs = _jobs()
    jobs._control_check(cancel, lease_lost)
    source_path = str(item["source_path"])
    partial_path = str(item["partial_path"])

    if not _source_stat_matches(source_endpoint, item):
        raise jobs.StreamCopySourceChanged(f"Source identity changed: {source_path}")
    if not endpoints.exists(destination_endpoint, partial_path):
        journal.discard_checkpoints_after(job_id, int(item["item_index"]), 0)
        return 0

    partial_size = int(endpoints.stat(destination_endpoint, partial_path)["size"])
    for checkpoint in journal.list_checkpoints(job_id, int(item["item_index"])):
        jobs._control_check(cancel, lease_lost)
        offset = int(checkpoint["offset"])
        block_start = int(checkpoint["block_start"])
        block_size = int(checkpoint["block_size"])
        expected = str(checkpoint["digest"])
        if offset > partial_size or block_start + block_size != offset:
            continue

        source_digest = _hash_range(
            source_endpoint,
            source_path,
            block_start,
            block_size,
        )
        partial_digest = _hash_range(
            destination_endpoint,
            partial_path,
            block_start,
            block_size,
        )
        if source_digest == expected and partial_digest == expected:
            journal.discard_checkpoints_after(
                job_id, int(item["item_index"]), offset
            )
            endpoints.truncate(destination_endpoint, partial_path, offset)
            return offset

    journal.discard_checkpoints_after(job_id, int(item["item_index"]), 0)
    endpoints.truncate(destination_endpoint, partial_path, 0)
    return 0


def _mark_skipped(job_id: str, item: dict[str, Any], message: str) -> None:
    jobs = _jobs()
    job = jobs._load_job(job_id)
    destination_endpoint = dict(job["destination_endpoint"])
    try:
        endpoints.remove_file(destination_endpoint, str(item["partial_path"]))
    except (OSError, RemoteConnectionError, KeyError):
        pass
    journal.discard_checkpoints_after(job_id, int(item["item_index"]), 0)
    journal.update_item(
        job_id,
        int(item["item_index"]),
        status="skipped",
        confirmed_offset=0,
        error=message,
    )
    jobs._append_warning(job_id, str(item["source_path"]), message)
    jobs._sync_durable_progress(job_id)


def _publish_completed_item(
    job_id: str,
    item: dict[str, Any],
    job: dict[str, Any],
    source_endpoint: dict[str, Any],
    destination_endpoint: dict[str, Any],
    *,
    partial: bool,
) -> None:
    source_path = str(item["source_path"])
    target_path = str(item["target_path"])
    partial_path = str(item["partial_path"])
    verification_target = partial_path if partial else target_path
    verify_mode = str(job.get("verify_mode") or "size")

    _verify_pair(
        source_endpoint,
        source_path,
        destination_endpoint,
        verification_target,
        verify_mode,
    )

    if partial:
        if endpoints.exists(destination_endpoint, target_path):
            raise FileExistsError(target_path)
        journal.update_item(
            job_id,
            int(item["item_index"]),
            status="publishing",
            error=None,
        )
        endpoints.rename(destination_endpoint, partial_path, target_path)

    journal.update_item(
        job_id,
        int(item["item_index"]),
        status="completed",
        confirmed_offset=int(item["size"]),
        error=None,
    )
    _jobs()._sync_durable_progress(job_id)

    if job.get("delete_source_after_verify"):
        endpoints.remove_file(source_endpoint, source_path)


def _copy_item(
    job_id: str,
    original: dict[str, Any],
    cancel: threading.Event,
    lease_lost: threading.Event,
) -> None:
    jobs = _jobs()
    item_index = int(original["item_index"])

    while True:
        jobs._control_check(cancel, lease_lost)
        _wait_for_endpoints(job_id, cancel, lease_lost)
        job = jobs._load_job(job_id)
        source_endpoint = dict(job["source_endpoint"])
        destination_endpoint = dict(job["destination_endpoint"])
        item = journal.get_item(job_id, item_index)
        source_path = str(item["source_path"])
        target_path = str(item["target_path"])
        partial_path = str(item["partial_path"])

        if item["status"] == "skipped":
            return

        if item["status"] == "completed":
            if not endpoints.exists(destination_endpoint, target_path):
                if endpoints.exists(source_endpoint, source_path):
                    journal.update_item(
                        job_id,
                        item_index,
                        status="pending",
                        confirmed_offset=0,
                        error="published target disappeared; recopying",
                    )
                    journal.discard_checkpoints_after(job_id, item_index, 0)
                    continue
                raise FileNotFoundError(
                    f"Completed target disappeared and source unavailable: {target_path}"
                )
            if endpoints.exists(source_endpoint, source_path):
                _verify_pair(
                    source_endpoint,
                    source_path,
                    destination_endpoint,
                    target_path,
                    "sha256" if job.get("delete_source_after_verify") else "size",
                )
                if job.get("delete_source_after_verify"):
                    endpoints.remove_file(source_endpoint, source_path)
            return

        if item["status"] == "publishing" and endpoints.exists(
            destination_endpoint, target_path
        ):
            _publish_completed_item(
                job_id,
                item,
                job,
                source_endpoint,
                destination_endpoint,
                partial=False,
            )
            return

        if endpoints.exists(destination_endpoint, target_path):
            _mark_skipped(
                job_id,
                item,
                f"destination exists; skipped: {target_path}",
            )
            return

        try:
            resume_offset = _safe_resume_offset(
                job_id,
                item,
                source_endpoint,
                destination_endpoint,
                cancel,
                lease_lost,
            )
        except (OSError, RemoteConnectionError, KeyError):
            current = jobs._load_job(job_id)
            if any(not state["available"] for state in _endpoint_states(current)):
                continue
            raise

        if not _source_stat_matches(source_endpoint, item):
            raise jobs.StreamCopySourceChanged(f"Source changed: {source_path}")

        endpoints.makedirs(destination_endpoint, endpoints.parent(destination_endpoint, partial_path))
        journal.update_item(job_id, item_index, status="in_progress", error=None)
        jobs._persist_job(
            job_id,
            status="running",
            current_item_index=item_index,
            current_path=source_path,
            error=None,
        )

        summary = journal.summarize_items(job_id)
        base_bytes = int(summary["completed_bytes"])
        jobs._progress_ram(job_id, base_bytes, resume_offset, source_path)

        stream_queue: queue.Queue[tuple[str, Any]] = queue.Queue(
            maxsize=int(job["profile"]["queue_depth"])
        )
        producer_stop = threading.Event()
        producer_error: list[BaseException] = []
        chunk_size = int(job["profile"]["chunk_bytes"])

        def producer() -> None:
            try:
                with endpoints.open_read(
                    source_endpoint,
                    source_path,
                    offset=resume_offset,
                ) as source_stream:
                    remaining = int(item["size"]) - resume_offset
                    while remaining > 0 and not producer_stop.is_set():
                        jobs._control_check(cancel, lease_lost)
                        data = source_stream.read(min(chunk_size, remaining))
                        if not data:
                            raise OSError(
                                f"Unexpected EOF after {int(item['size']) - remaining} bytes"
                            )
                        while not producer_stop.is_set():
                            try:
                                stream_queue.put(("data", data), timeout=0.2)
                                break
                            except queue.Full:
                                jobs._control_check(cancel, lease_lost)
                        remaining -= len(data)
            except BaseException as exc:  # noqa: BLE001
                producer_error.append(exc)
            finally:
                while not producer_stop.is_set():
                    try:
                        stream_queue.put(("done", None), timeout=0.2)
                        break
                    except queue.Full:
                        continue

        producer_thread = threading.Thread(
            target=producer,
            daemon=True,
            name=f"remote-river-producer-{job_id[:8]}-{item_index}",
        )
        producer_thread.start()

        offset = resume_offset
        block_start = resume_offset
        block_digest = hashlib.sha256()
        copy_error: BaseException | None = None

        try:
            if endpoints.exists(destination_endpoint, partial_path):
                endpoints.truncate(destination_endpoint, partial_path, resume_offset)
            with endpoints.open_write(
                destination_endpoint,
                partial_path,
                offset=resume_offset,
            ) as destination_stream:
                while True:
                    jobs._control_check(cancel, lease_lost)
                    try:
                        kind, payload = stream_queue.get(timeout=0.5)
                    except queue.Empty:
                        if producer_thread.is_alive():
                            continue
                        kind, payload = ("done", None)
                    if kind == "done":
                        break
                    data = payload
                    written = destination_stream.write(data)
                    if written != len(data):
                        raise OSError(
                            f"Short write: expected {len(data)}, wrote {written}"
                        )
                    block_digest.update(data)
                    offset += len(data)
                    jobs._progress_ram(job_id, base_bytes, offset, source_path)

                    if offset - block_start == jobs.CHECKPOINT_BYTES:
                        endpoints.flush(destination_stream, destination_endpoint)
                        journal.add_checkpoint(
                            job_id,
                            item_index,
                            offset=offset,
                            block_start=block_start,
                            block_size=offset - block_start,
                            digest=block_digest.hexdigest(),
                        )
                        jobs._sync_durable_progress(job_id, offset)
                        block_start = offset
                        block_digest = hashlib.sha256()
                    elif offset - block_start > jobs.CHECKPOINT_BYTES:
                        raise RuntimeError(
                            "Remote River checkpoint alignment invariant failed"
                        )
                endpoints.flush(destination_stream, destination_endpoint)
        except BaseException as exc:  # noqa: BLE001
            copy_error = exc
        finally:
            producer_stop.set()
            producer_thread.join(timeout=3)

        if copy_error is None and producer_error:
            copy_error = producer_error[0]

        if copy_error is not None:
            if isinstance(
                copy_error,
                (jobs.StreamCopyCancelled, jobs.StreamCopyLeaseLost),
            ):
                raise copy_error
            current = jobs._load_job(job_id)
            if any(not state["available"] for state in _endpoint_states(current)):
                log_warning(
                    "streamcopy.remote_flow_interrupted",
                    job_id=job_id,
                    item_index=item_index,
                    path=source_path,
                    error=f"{type(copy_error).__name__}: {copy_error}",
                )
                continue
            if not _source_stat_matches(source_endpoint, item):
                _mark_skipped(
                    job_id,
                    item,
                    f"{type(copy_error).__name__}: {copy_error}",
                )
                return
            raise copy_error

        if offset != int(item["size"]):
            raise OSError(
                f"Stream length mismatch for {source_path}: "
                f"expected {item['size']}, got {offset}"
            )

        try:
            _publish_completed_item(
                job_id,
                item,
                jobs._load_job(job_id),
                source_endpoint,
                destination_endpoint,
                partial=True,
            )
            return
        except (OSError, RemoteConnectionError, KeyError):
            current = jobs._load_job(job_id)
            if any(not state["available"] for state in _endpoint_states(current)):
                continue
            raise


def _remove_empty_source_tree(job: dict[str, Any]) -> None:
    if not job.get("delete_source_after_verify"):
        return
    source_endpoint = dict(job["source_endpoint"])
    source_path = str(job["source_path"])
    try:
        info = endpoints.stat(source_endpoint, source_path)
    except (OSError, FileNotFoundError, RemoteNotFound, RemoteConnectionError, KeyError):
        return
    if not info["is_dir"]:
        return

    directories: list[str] = []
    stack = [source_path]
    while stack:
        current = stack.pop()
        directories.append(current)
        try:
            entries = endpoints.listdir(source_endpoint, current)
        except (OSError, RemoteConnectionError, KeyError):
            return
        for entry in entries:
            if entry["is_dir"] and not entry.get("is_symlink"):
                stack.append(str(entry["path"]))

    for directory in sorted(
        directories,
        key=lambda value: value.count("/") if source_endpoint["kind"] == "remote"
        else len(Path(value).parts),
        reverse=True,
    ):
        try:
            endpoints.remove_dir(source_endpoint, directory)
        except (OSError, RemoteConnectionError, KeyError):
            pass


def _heartbeat(
    job_id: str,
    stop: threading.Event,
    lease_lost: threading.Event,
) -> None:
    jobs = _jobs()
    while not stop.wait(jobs.LEASE_HEARTBEAT_SECONDS):
        try:
            if not journal.renew_lease(
                job_id, jobs._INSTANCE_ID, jobs.LEASE_SECONDS
            ):
                lease_lost.set()
                return
        except Exception:  # noqa: BLE001
            lease_lost.set()
            return


def run_remote_job(job_id: str) -> None:
    jobs = _jobs()
    cancel = jobs._cancel_events[job_id]
    lease_lost = threading.Event()
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat,
        args=(job_id, heartbeat_stop, lease_lost),
        daemon=True,
        name=f"remote-river-heartbeat-{job_id[:8]}",
    )
    heartbeat_thread.start()

    try:
        _wait_for_endpoints(job_id, cancel, lease_lost)
        items = journal.list_items(job_id)
        if not items:
            jobs._persist_job(job_id, status="planning", error=None)
            while not items:
                jobs._control_check(cancel, lease_lost)
                _wait_for_endpoints(job_id, cancel, lease_lost)
                try:
                    _build_manifest(job_id)
                    items = journal.list_items(job_id)
                except (OSError, RemoteConnectionError, KeyError):
                    current = jobs._load_job(job_id)
                    if any(
                        not state["available"]
                        for state in _endpoint_states(current)
                    ):
                        continue
                    raise

        with jobs._lock:
            cached = jobs._jobs.get(job_id)
            if cached is not None:
                import time

                cached["_transfer_started_monotonic"] = time.monotonic()
                cached["_session_start_bytes"] = int(cached.get("bytes") or 0)

        jobs._persist_job(job_id, status="recovering", error=None)
        for item in items:
            while True:
                jobs._control_check(cancel, lease_lost)
                try:
                    _copy_item(job_id, item, cancel, lease_lost)
                    break
                except (RemoteConnectionError, OSError, KeyError):
                    current = jobs._load_job(job_id)
                    if any(
                        not state["available"]
                        for state in _endpoint_states(current)
                    ):
                        _wait_for_endpoints(job_id, cancel, lease_lost)
                        continue
                    raise

        job = jobs._load_job(job_id)
        _remove_empty_source_tree(job)
        summary = journal.summarize_items(job_id)
        warnings = list(job.get("warnings") or [])
        status = (
            "completed_with_warnings"
            if warnings or summary["skipped_files"]
            else "completed"
        )
        jobs._persist_job(
            job_id,
            status=status,
            bytes=int(summary["completed_bytes"]),
            files=int(summary["completed_files"]),
            skipped=max(
                int(job.get("skipped") or 0),
                int(summary["skipped_files"]),
            ),
            skipped_bytes=int(summary["skipped_bytes"]),
            progress_percent=100.0,
            current_item_index=None,
            current_path="",
            error=None,
            finished_at=jobs._now(),
        )
        logger = log_warning if status == "completed_with_warnings" else log_event
        logger(
            f"streamcopy.remote_{status}",
            job_id=job_id,
            files=summary["completed_files"],
            bytes=summary["completed_bytes"],
            skipped=summary["skipped_files"],
        )
    except jobs.StreamCopyCancelled as exc:
        jobs._persist_job(
            job_id,
            status="cancelled",
            error=str(exc),
            finished_at=jobs._now(),
            current_path="",
        )
        log_event("streamcopy.remote_cancelled", job_id=job_id)
    except jobs.StreamCopyLeaseLost as exc:
        log_error("streamcopy.remote_lease_lost", job_id=job_id, error=str(exc))
    except BaseException as exc:  # noqa: BLE001
        jobs._persist_job(
            job_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            finished_at=jobs._now(),
        )
        log_error(
            "streamcopy.remote_failed",
            job_id=job_id,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)
        journal.release_lease(job_id, jobs._INSTANCE_ID)
        with jobs._lock:
            jobs._cancel_events.pop(job_id, None)
            jobs._threads.pop(job_id, None)
            jobs._event_last_emit.pop(job_id, None)


def start_remote_streamcopy_job(
    *,
    source_path: str,
    destination_path: str,
    source_kind: str,
    destination_kind: str,
    source_connection_id: str | None,
    destination_connection_id: str | None,
    source_media: str,
    destination_media: str,
    source_transport: str,
    destination_transport: str,
    usb_topology: str,
    source_cache_mib: int | float | str | None,
    destination_cache_mib: int | float | str | None,
    ordering_mode: str,
    verify_mode: str,
    delete_source_after_verify: bool,
) -> dict[str, Any]:
    jobs = _jobs()
    source_endpoint = endpoints.make_endpoint(
        source_kind,
        source_path,
        source_connection_id,
    )
    destination_endpoint = endpoints.make_endpoint(
        destination_kind,
        destination_path,
        destination_connection_id,
    )
    source_path = str(source_endpoint["path"])
    destination_path = str(destination_endpoint["path"])

    source_info = endpoints.stat(source_endpoint, source_path)
    if source_info.get("is_symlink"):
        raise ValueError("source root cannot be a symlink")

    if endpoints.same_namespace(source_endpoint, destination_endpoint):
        if source_endpoint["kind"] == "remote":
            src_cmp = endpoints.normalize_remote_path(source_path)
            dst_cmp = endpoints.normalize_remote_path(destination_path)
            if src_cmp == dst_cmp:
                raise ValueError("destination cannot be the source")
            if source_info["is_dir"] and (
                dst_cmp == src_cmp or dst_cmp.startswith(src_cmp.rstrip("/") + "/")
            ):
                raise ValueError("destination cannot be nested inside source")
        else:
            source_resolved = Path(source_path).resolve(strict=True)
            destination_resolved = Path(destination_path).resolve(strict=False)
            if source_resolved == destination_resolved:
                raise ValueError("destination cannot be the source")
            if source_info["is_dir"]:
                try:
                    destination_resolved.relative_to(source_resolved)
                except ValueError:
                    pass
                else:
                    raise ValueError("destination cannot be nested inside source")

    endpoints.makedirs(destination_endpoint, destination_path)
    destination_info = endpoints.stat(destination_endpoint, destination_path)
    if not destination_info["is_dir"]:
        raise NotADirectoryError(destination_path)

    mode = str(verify_mode or "size").casefold()
    if mode not in {"size", "sha256"}:
        raise ValueError("verify_mode must be size or sha256")
    delete_after = bool(delete_source_after_verify)
    if delete_after:
        mode = "sha256"

    source_transport = (
        "network" if source_endpoint["kind"] == "remote" else source_transport
    )
    destination_transport = (
        "network"
        if destination_endpoint["kind"] == "remote"
        else destination_transport
    )
    profile = jobs.stream_profile(
        source_media,
        destination_media,
        source_transport,
        destination_transport,
        usb_topology,
        source_cache_mib,
        destination_cache_mib,
        ordering_mode,
    )
    profile["remote_river"] = True
    profile["microfile_batching"] = False
    profile["ordering_mode"] = "manifest"
    profile["ordering"] = (
        "persistent manifest / SFTP River Keeper checkpoints / sequential items"
    )
    profile["remote_note"] = (
        "Remote River uses SFTP only. Credentials remain RAM-only and are rebound "
        "after restart by stable endpoint identity."
    )

    import time
    import uuid

    job_id = uuid.uuid4().hex
    created = jobs._now()
    job = {
        "id": job_id,
        "type": "streamcopy_experimental",
        "status": "planning",
        "source_path": source_path,
        "destination_path": destination_path,
        "source_endpoint": source_endpoint,
        "destination_endpoint": destination_endpoint,
        "profile": profile,
        "verify_mode": mode,
        "delete_source_after_verify": delete_after,
        "target_root": None,
        "current_item_index": None,
        "current_path": "",
        "bytes": 0,
        "total_bytes": 0,
        "files": 0,
        "total_files": 0,
        "skipped": 0,
        "skipped_bytes": 0,
        "manifest_files": 0,
        "manifest_directories": 0,
        "warnings": [],
        "error": None,
        "progress_percent": 0.0,
        "average_mib_s": 0.0,
        "wait_cycles": 0,
        "auto_resumes": 0,
        "waiting_since": None,
        "lease_owner": jobs._INSTANCE_ID,
        "lease_expires_at": time.time() + jobs.LEASE_SECONDS,
        "created_at": created,
        "updated_at": created,
        "finished_at": None,
        "persistent": True,
    }
    journal.create_job(job)
    jobs._cache_job(job)
    if not journal.claim_job(job_id, jobs._INSTANCE_ID, jobs.LEASE_SECONDS):
        raise RuntimeError("could not claim new Remote River job")
    jobs._spawn_claimed_job(job_id)
    log_event(
        "streamcopy.remote_started",
        job_id=job_id,
        source_kind=source_endpoint["kind"],
        destination_kind=destination_endpoint["kind"],
        source=source_path,
        destination=destination_path,
        verify_mode=mode,
        delete_source_after_verify=delete_after,
    )
    return jobs.get_streamcopy_job(job_id)
