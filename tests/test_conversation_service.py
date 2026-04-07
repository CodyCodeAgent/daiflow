"""Tests for conversation service — init logic, code copy, skill sync."""

import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from daiflow.config import CONVERSATIONS_DIR, PROJECTS_DIR
from daiflow.models import Conversation, ConversationStatus, Project, ProjectRepo, Session, SessionStatus
from daiflow.services.conversation_service import (
    _copy_code_to_conversation,
    delete_conversation_dir,
    get_conversation_context,
    resolve_conversation_roots,
)


class TestCopyCodeToConversation:
    def test_copies_git_repos(self, tmp_path):
        """Git repos are copied from project to conversation dir."""
        project_dir = tmp_path / "projects" / "proj1"
        (project_dir / "code" / "my-repo").mkdir(parents=True)
        (project_dir / "code" / "my-repo" / "main.py").write_text("print('hello')")
        # Simulate a .git directory
        (project_dir / "code" / "my-repo" / ".git").mkdir()
        (project_dir / "code" / "my-repo" / ".git" / "config").write_text("git config")

        conv_dir = tmp_path / "conversations" / "conv1"
        conv_dir.mkdir(parents=True)

        repo = type('Repo', (), {'git_url': 'https://github.com/org/my-repo.git', 'local_path': ''})()

        with patch("daiflow.services.conversation_service.get_project_dir", return_value=project_dir), \
             patch("daiflow.services.conversation_service.get_conversation_dir", return_value=conv_dir):
            _copy_code_to_conversation("proj1", "conv1", [repo])

        dst = conv_dir / "code" / "my-repo"
        assert dst.exists()
        assert (dst / "main.py").read_text() == "print('hello')"
        # .git should be removed
        assert not (dst / ".git").exists()

    def test_skips_local_path_repos(self, tmp_path):
        """Repos with local_path should NOT be copied."""
        project_dir = tmp_path / "projects" / "proj1"
        project_dir.mkdir(parents=True)
        conv_dir = tmp_path / "conversations" / "conv1"
        conv_dir.mkdir(parents=True)

        repo = type('Repo', (), {'git_url': '', 'local_path': '/some/local/path'})()

        with patch("daiflow.services.conversation_service.get_project_dir", return_value=project_dir), \
             patch("daiflow.services.conversation_service.get_conversation_dir", return_value=conv_dir):
            _copy_code_to_conversation("proj1", "conv1", [repo])

        assert not (conv_dir / "code").exists()


class TestResolveConversationRoots:
    def test_local_path_repos(self, tmp_path):
        repo = type('Repo', (), {'git_url': '', 'local_path': '/my/project'})()
        with patch("daiflow.services.conversation_service.get_conversation_dir", return_value=tmp_path):
            roots = resolve_conversation_roots("conv1", [repo])
        assert roots == ['/my/project']

    def test_git_repos(self, tmp_path):
        repo = type('Repo', (), {'git_url': 'https://github.com/org/my-repo.git', 'local_path': ''})()
        with patch("daiflow.services.conversation_service.get_conversation_dir", return_value=tmp_path):
            roots = resolve_conversation_roots("conv1", [repo])
        assert roots == [str(tmp_path / "code" / "my-repo")]


class TestDeleteConversationDir:
    def test_deletes_existing_dir(self):
        conv_dir = CONVERSATIONS_DIR / "test_delete_conv"
        conv_dir.mkdir(parents=True, exist_ok=True)
        (conv_dir / "file.txt").write_text("test")
        delete_conversation_dir("test_delete_conv")
        assert not conv_dir.exists()

    def test_no_error_if_missing(self):
        # Should not raise
        delete_conversation_dir("nonexistent_conv_999")


class TestGetConversationContext:
    async def test_returns_repos_and_roots(self, db_session):
        project = Project(name="Test")
        db_session.add(project)
        await db_session.flush()

        repo = ProjectRepo(
            project_id=project.id,
            git_url="https://github.com/org/repo.git",
        )
        db_session.add(repo)
        await db_session.commit()

        repos, roots = await get_conversation_context(db_session, "conv1", project.id)
        assert len(repos) == 1
        assert len(roots) == 1
        assert "repo" in roots[0]
