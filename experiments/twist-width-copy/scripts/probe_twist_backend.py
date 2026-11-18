"""Bounded preflight, standard library only. Does not install packages or download weights."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=Path("models/sam-3d-body"))
    parser.add_argument("--torch-python", type=Path, help="Read-only compatibility probe subprocess")
    parser.add_argument("--network", action="store_true", help="Read public model metadata and up to 128 checkpoint bytes")
    args = parser.parse_args()
    started = time.perf_counter()
    result = dict(probe_version="0.1.0", platform=platform.platform(), python=sys.version,
                  inference_status="unverified", model_dir=str(args.model_dir), assets={}, network=[])
    for name in ("model.ckpt", "model_config.yaml", "assets/mhr_model.pt"):
        path = args.model_dir / name
        result["assets"][name] = dict(available=path.is_file())
        if path.is_file():
            with path.open("rb") as stream:
                result["assets"][name]["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    result["hf_token_configured"] = bool(os.environ.get("HF_TOKEN")) or any(p.is_file() for p in (
        Path.home() / ".cache/huggingface/token", Path.home() / ".huggingface/token"))
    if args.torch_python:
        code = "import torch,json;print(json.dumps(dict(torch=torch.__version__,cuda=torch.version.cuda,available=torch.cuda.is_available(),device=torch.cuda.get_device_name() if torch.cuda.is_available() else None,capability=torch.cuda.get_device_capability() if torch.cuda.is_available() else None,bfloat16=torch.cuda.is_bf16_supported() if torch.cuda.is_available() else None)))"
        try:
            proc = subprocess.run([str(args.torch_python.resolve()), "-c", code], capture_output=True, text=True, timeout=30)
            result["existing_tracker_torch_probe"] = dict(exit_code=proc.returncode, stdout=proc.stdout.strip(), stderr=proc.stderr[-1000:])
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["existing_tracker_torch_probe"] = dict(error=str(exc))
    if args.network:
        for name in ("model_config.yaml", "model.ckpt", "assets/mhr_model.pt"):
            url = "https://huggingface.co/facebook/sam-3d-body-dinov3/resolve/main/" + name
            record = dict(url=url, authentication="anonymous", max_bytes=128)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-127"}), timeout=10) as response:
                    record.update(status=response.status, bytes_read=len(response.read(128)))
            except urllib.error.HTTPError as exc:
                record.update(status=exc.code, error=exc.read(500).decode(errors="replace"))
            except OSError as exc:
                record["error"] = str(exc)
            result["network"].append(record)
    result.update(wall_seconds=time.perf_counter() - started,
                  blockers=["local model assets absent"] if not all(v["available"] for v in result["assets"].values()) else [],
                  measured_model_runtime_seconds=None, measured_model_peak_memory_bytes=None,
                  note="Preflight is not model inference. No GPU compatibility or accuracy claim.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote preflight to {args.output}; inference remains unverified")


if __name__ == "__main__":
    main()
