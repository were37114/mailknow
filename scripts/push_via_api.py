#!/usr/bin/env python3
"""Push local git commits to GitHub via REST API (when git push is blocked).

Usage: GITHUB_TOKEN=ghp_xxx python3 push_via_api.py
"""
import json, os, subprocess, sys, base64, urllib.request, urllib.error

REPO = os.environ.get("GITHUB_REPO", "were37114/MailKnow")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = f"https://api.github.com/repos/{REPO}"
HEADERS = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json"}

if not TOKEN:
    print("Error: GITHUB_TOKEN env var required"); sys.exit(1)

def api_call(method, path, data=None):
    url = f"{API}{path}" if path.startswith("/") else path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

def api_call_no_raise(method, path, data=None):
    try: return api_call(method, path, data)
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        raise

def upload_blob(content_bytes):
    content_b64 = base64.b64encode(content_bytes).decode()
    resp = api_call("POST", "/git/blobs", {"content": content_b64, "encoding": "base64"})
    return resp["sha"]

def get_commit_tree_entries(sha):
    result = subprocess.run(["git", "ls-tree", "-r", sha], capture_output=True, text=True, cwd=os.getcwd())
    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line: continue
        meta, path = line.split("\t", 1)
        mode, obj_type, blob_sha = meta.split()
        entries.append({"mode": mode, "type": "blob", "sha": blob_sha, "path": path})
    return entries

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    os.chdir("..")
    ref = api_call("GET", "/git/refs/heads/main")
    remote_sha = ref["object"]["sha"]
    print(f"Remote main: {remote_sha[:8]}")
    result = subprocess.run(["git", "log", "--reverse", "--format=%H|%s|%an|%ae|%aI", f"{remote_sha}..HEAD"], capture_output=True, text=True, cwd=os.getcwd())
    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line: continue
        parts = line.split("|", 4)
        commits.append({"sha": parts[0], "message": parts[1], "author_name": parts[2], "author_email": parts[3], "date": parts[4]})
    if not commits: print("Nothing to push!"); return
    print(f"Pushing {len(commits)} commits...")
    current_remote_sha = remote_sha
    for i, commit in enumerate(commits):
        print(f"\nCommit {i+1}/{len(commits)}: {commit['sha'][:8]} - {commit['message'][:60]}")
        entries = get_commit_tree_entries(commit["sha"])
        print(f"  Tree has {len(entries)} files")
        uploaded = 0
        for entry in entries:
            existing = api_call_no_raise("GET", f"/git/blobs/{entry['sha']}")
            if existing is None:
                result = subprocess.run(["git", "cat-file", "-p", entry["sha"]], capture_output=True, cwd=os.getcwd())
                new_sha = upload_blob(result.stdout)
                uploaded += 1
        print(f"  Uploaded {uploaded} new blobs")
        resp = api_call("POST", "/git/trees", {"tree": entries})
        new_tree_sha = resp["sha"]
        resp = api_call("POST", "/git/commits", {"message": commit["message"], "tree": new_tree_sha, "parents": [current_remote_sha], "author": {"name": commit["author_name"], "email": commit["author_email"], "date": commit["date"]}})
        current_remote_sha = resp["sha"]
        print(f"  Created commit {current_remote_sha[:8]}")
    print(f"\nUpdating main to {current_remote_sha[:8]}...")
    api_call("PATCH", "/git/refs/heads/main", {"sha": current_remote_sha, "force": False})
    print("Push complete!")

if __name__ == "__main__":
    main()
