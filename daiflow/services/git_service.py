import asyncio
import logging
import re

logger = logging.getLogger(__name__)

# Valid git branch name: starts with word char, allows word chars, dots, slashes, hyphens
_BRANCH_RE = re.compile(r'^[\w][\w./-]*$')


def validate_branch_name(branch: str):
    """Validate that a branch name is safe for git commands.

    Rejects names that could be interpreted as git flags (starting with -)
    or contain characters invalid for filenames/git refs.
    """
    if not branch or not _BRANCH_RE.match(branch):
        raise ValueError(f"Invalid branch name: {branch!r}")
    if '..' in branch or branch.endswith('.lock') or branch.endswith('/'):
        raise ValueError(f"Invalid branch name: {branch!r}")


async def _run(cmd: list[str], cwd: str, timeout: int = 120) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Git operation timed out after {timeout}s")
    if proc.returncode != 0:
        stderr_text = stderr.decode().strip()
        # Log full details for debugging, return sanitized message to caller
        logger.error("Git command failed: %s | stderr: %s", " ".join(cmd), stderr_text)
        # Provide a user-friendly error without exposing full paths
        short_cmd = cmd[1] if len(cmd) > 1 else cmd[0]
        raise RuntimeError(f"Git {short_cmd} failed: {stderr_text[:200]}")
    return stdout.decode().strip()


async def clone_or_pull(git_url: str, target_dir: str, timeout: int = 300) -> str:
    """Clone a repo if not yet cloned, otherwise pull latest.

    Returns the absolute path to the cloned repo directory.
    """
    from pathlib import Path

    target = Path(target_dir)
    if (target / ".git").exists():
        logger.info("Repo already cloned at %s, pulling latest...", target_dir)
        await _run(["git", "pull", "--ff-only"], cwd=target_dir, timeout=timeout)
    else:
        target.mkdir(parents=True, exist_ok=True)
        logger.info("Cloning %s into %s ...", git_url, target_dir)
        await _run(["git", "clone", git_url, target_dir], cwd=str(target.parent), timeout=timeout)
    return target_dir


async def checkout_branch(local_path: str, branch: str):
    """Checkout or create a branch. Creates if it doesn't exist."""
    validate_branch_name(branch)
    try:
        await _run(["git", "checkout", "-b", branch], cwd=local_path)
    except RuntimeError:
        # Branch already exists — just switch to it
        await _run(["git", "checkout", branch], cwd=local_path)


async def get_diff(local_path: str, branch: str = "") -> str:
    """Get git diff for the current branch against its merge-base with main.

    Uses `git add -N .` first to include untracked (new) files in the diff.
    This only registers new files in the index without staging their content,
    so it won't affect commits.
    """
    # Make untracked files visible to git diff
    try:
        await _run(["git", "add", "-N", "."], cwd=local_path)
    except RuntimeError:
        pass

    if branch:
        validate_branch_name(branch)
        # Try to diff against merge-base with common default branches
        for base in ("main", "master"):
            try:
                merge_base = await _run(["git", "merge-base", base, branch], cwd=local_path)
                return await _run(["git", "diff", merge_base], cwd=local_path)
            except RuntimeError:
                continue
        # Fallback: diff against HEAD (shows uncommitted changes)
        logger.info("No main/master base found for branch %s, falling back to HEAD diff", branch)
        return await _run(["git", "diff", "HEAD"], cwd=local_path)
    return await _run(["git", "diff", "HEAD"], cwd=local_path)


async def get_head_hash(local_path: str) -> str:
    """Get the current HEAD commit hash."""
    return await _run(["git", "rev-parse", "HEAD"], cwd=local_path)


async def get_diff_between(local_path: str, hash_before: str, hash_after: str) -> str:
    """Get diff between two commit hashes."""
    return await _run(["git", "diff", hash_before, hash_after], cwd=local_path)


async def commit(local_path: str, message: str):
    """Stage all changes and commit.

    Uses 'git add .' which respects .gitignore rules.
    """
    await _run(["git", "add", "."], cwd=local_path)
    await _run(["git", "commit", "-m", message], cwd=local_path)


async def push(local_path: str, branch: str) -> str | None:
    """Push to remote. Returns MR/PR URL parsed from push output if available."""
    validate_branch_name(branch)
    cmd = ["git", "push", "-u", "origin", branch]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=local_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("Git push timed out after 120s")
    if proc.returncode != 0:
        stderr_text = stderr.decode().strip()
        logger.error("Git command failed: git push | stderr: %s", stderr_text)
        raise RuntimeError(f"Git push failed: {stderr_text[:200]}")
    # GitHub/GitLab print the compare/create-MR URL in stderr on successful push
    match = re.search(r'https?://\S+', stderr.decode())
    return match.group(0).rstrip('.') if match else None


async def create_pr(local_path: str, title: str, body: str = "") -> str | None:
    """Create a pull request using GitHub CLI (gh).

    Returns the PR URL if successful, None if gh is not available or fails.
    """
    import shutil

    # Check if gh is available
    gh_path = shutil.which("gh")
    if not gh_path:
        logger.warning("gh CLI not found, cannot create PR automatically")
        return None

    try:
        # Create PR and capture the URL from output
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "create",
            "--title", title,
            "--body", body if body else title,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=local_path,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode != 0:
            stderr_text = stderr.decode().strip()
            logger.error("gh pr create failed: %s", stderr_text)
            return None

        # Output is typically the PR URL
        pr_url = stdout.decode().strip()
        logger.info("PR created: %s", pr_url)
        return pr_url

    except asyncio.TimeoutError:
        logger.error("gh pr create timed out")
        return None
    except Exception as e:
        logger.error("Failed to create PR with gh: %s", e)
        return None


async def fetch_remote(local_path: str, timeout: int = 120) -> None:
    """Fetch latest from origin."""
    await _run(["git", "fetch", "origin"], cwd=local_path, timeout=timeout)


async def get_remote_head(local_path: str, branch: str = "") -> tuple[str | None, str | None]:
    """Get the commit hash and branch name of a remote branch (origin/<branch>).

    Tries origin/main then origin/master if branch is not specified.
    Returns (hash, branch_name) or (None, None) if no remote branch found.
    """
    candidates = [branch] if branch else ["main", "master"]
    for b in candidates:
        try:
            h = await _run(["git", "rev-parse", f"origin/{b}"], cwd=local_path)
            return h, b
        except RuntimeError:
            continue
    return None, None


async def merge_ff_only(local_path: str, remote_branch: str) -> None:
    """Fast-forward merge from a remote tracking branch. Use after fetch_remote()."""
    validate_branch_name(remote_branch)
    await _run(["git", "merge", "--ff-only", f"origin/{remote_branch}"], cwd=local_path)


def generate_mr_link(git_url: str, branch: str) -> str | None:
    """Generate a merge request / pull request link from git URL and branch.

    Supports GitHub, GitLab, Gitee, and Bitbucket.
    Returns None if the URL format is not recognized.
    """
    if not git_url or not branch:
        return None

    # Normalize URL (remove .git suffix and trailing slashes)
    url = git_url.rstrip("/").removesuffix(".git")

    # Extract host and path
    if not url.startswith(("http://", "https://", "git@")):
        return None

    # Handle SSH URLs (git@host:path)
    if url.startswith("git@"):
        # git@github.com:user/repo -> https://github.com/user/repo
        url = "https://" + url[4:].replace(":", "/", 1)

    # Parse URL
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lstrip("/")
    except Exception:
        return None

    if not path:
        return None

    # Generate MR/PR link based on platform
    if "github.com" in host:
        return f"https://{host}/{path}/compare/{branch}?expand=1"
    elif "gitlab.com" in host or "gitlab" in host:
        return f"https://{host}/{path}/-/merge_requests/new?merge_request[source_branch]={branch}"
    elif "gitee.com" in host or "gitee" in host:
        return f"https://{host}/{path}/pull_requests/new?pull_request[source_branch]={branch}"
    elif "bitbucket.org" in host or "bitbucket" in host:
        return f"https://{host}/{path}/pull-requests/new?source={branch}"
    else:
        # Generic fallback - try to create a reasonable link
        return f"https://{host}/{path}/pulls/new?source={branch}"
