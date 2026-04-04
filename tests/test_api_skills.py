"""Tests for Skill Center API endpoints and core service functions."""

import json

from daiflow.models import Project, ProjectSkill, Skill, Task, TaskSkill


# ── Skill CRUD ──


class TestSkillCRUD:
    async def test_list_empty(self, client):
        resp = await client.get("/api/skills")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_skill(self, client):
        resp = await client.post("/api/skills", json={
            "name": "coding-standards",
            "description": "Team coding conventions",
            "content": "# Standards\n\nUse 4 spaces.",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "coding-standards"
        assert data["source_type"] == "manual"
        assert data["source_id"] == "0"
        assert data["content"] == "# Standards\n\nUse 4 spaces."
        assert data["id"]

    async def test_create_skill_trims_name(self, client):
        resp = await client.post("/api/skills", json={
            "name": "  spaces  ",
            "content": "body",
        })
        assert resp.status_code == 201
        assert resp.json()["name"] == "spaces"

    async def test_create_skill_empty_name(self, client):
        resp = await client.post("/api/skills", json={
            "name": "  ",
            "content": "body",
        })
        assert resp.status_code == 422

    async def test_upsert_same_key(self, client):
        """POST with same (source_type, source_id, name) updates existing."""
        resp1 = await client.post("/api/skills", json={
            "name": "test-skill",
            "description": "v1",
            "content": "old",
        })
        id1 = resp1.json()["id"]

        resp2 = await client.post("/api/skills", json={
            "name": "test-skill",
            "description": "v2",
            "content": "new",
        })
        id2 = resp2.json()["id"]
        assert id1 == id2
        assert resp2.json()["description"] == "v2"
        assert resp2.json()["content"] == "new"

    async def test_get_skill(self, client):
        create = await client.post("/api/skills", json={"name": "s1", "content": "c1"})
        sid = create.json()["id"]

        resp = await client.get(f"/api/skills/{sid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "s1"
        assert resp.json()["content"] == "c1"

    async def test_get_skill_not_found(self, client):
        resp = await client.get("/api/skills/nonexistent")
        assert resp.status_code == 404

    async def test_update_skill(self, client):
        create = await client.post("/api/skills", json={"name": "s1", "content": "old"})
        sid = create.json()["id"]

        resp = await client.put(f"/api/skills/{sid}", json={"content": "new", "description": "updated"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "new"
        assert resp.json()["description"] == "updated"

    async def test_delete_skill(self, client):
        create = await client.post("/api/skills", json={"name": "del-me", "content": "x"})
        sid = create.json()["id"]

        resp = await client.delete(f"/api/skills/{sid}")
        assert resp.status_code == 204

        resp2 = await client.get(f"/api/skills/{sid}")
        assert resp2.status_code == 404

    async def test_list_with_source_type_filter(self, client):
        await client.post("/api/skills", json={"name": "m1", "content": "x", "source_type": "manual"})
        await client.post("/api/skills", json={"name": "e1", "content": "x", "source_type": "external", "source_id": "0"})

        resp = await client.get("/api/skills?source_type=manual")
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()]
        assert "m1" in names
        assert "e1" not in names

    async def test_create_project_skill_validates_project(self, client):
        """source_type=project with non-existent project_id should 404."""
        resp = await client.post("/api/skills", json={
            "name": "test",
            "content": "x",
            "source_type": "project",
            "source_id": "fake_project_id",
        })
        assert resp.status_code == 404


# ── Project-Skill Associations ──


class TestProjectSkillAssociations:
    async def _create_project(self, client, name="Test Project"):
        resp = await client.post("/api/projects", json={"name": name})
        return resp.json()["id"]

    async def _create_skill(self, client, name="test-skill"):
        resp = await client.post("/api/skills", json={"name": name, "content": "body"})
        return resp.json()["id"]

    async def test_list_project_skills_empty(self, client):
        pid = await self._create_project(client)
        resp = await client.get(f"/api/projects/{pid}/skills")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_link_and_list(self, client):
        pid = await self._create_project(client)
        sid = await self._create_skill(client)

        link_resp = await client.post(f"/api/projects/{pid}/skills/{sid}")
        assert link_resp.status_code == 200

        list_resp = await client.get(f"/api/projects/{pid}/skills")
        assert len(list_resp.json()) == 1
        assert list_resp.json()[0]["name"] == "test-skill"

    async def test_link_idempotent(self, client):
        pid = await self._create_project(client)
        sid = await self._create_skill(client)

        await client.post(f"/api/projects/{pid}/skills/{sid}")
        await client.post(f"/api/projects/{pid}/skills/{sid}")

        list_resp = await client.get(f"/api/projects/{pid}/skills")
        assert len(list_resp.json()) == 1

    async def test_unlink(self, client):
        pid = await self._create_project(client)
        sid = await self._create_skill(client)

        await client.post(f"/api/projects/{pid}/skills/{sid}")
        resp = await client.delete(f"/api/projects/{pid}/skills/{sid}")
        assert resp.status_code == 200

        list_resp = await client.get(f"/api/projects/{pid}/skills")
        assert len(list_resp.json()) == 0

    async def test_link_nonexistent_skill(self, client):
        pid = await self._create_project(client)
        resp = await client.post(f"/api/projects/{pid}/skills/fake_id")
        assert resp.status_code == 404

    async def test_link_nonexistent_project(self, client):
        sid = await self._create_skill(client)
        resp = await client.post(f"/api/projects/fake_id/skills/{sid}")
        assert resp.status_code == 404

    async def test_auto_link_on_project_skill_create(self, client):
        """Creating a skill with source_type=project auto-links to that project."""
        pid = await self._create_project(client)
        await client.post("/api/skills", json={
            "name": "auto-linked",
            "content": "x",
            "source_type": "project",
            "source_id": pid,
        })

        list_resp = await client.get(f"/api/projects/{pid}/skills")
        names = [s["name"] for s in list_resp.json()]
        assert "auto-linked" in names

    async def test_list_skills_by_project_id(self, client):
        """GET /api/skills?project_id=xxx returns only linked skills."""
        pid = await self._create_project(client)
        await client.post("/api/skills", json={
            "name": "linked", "content": "x", "source_type": "project", "source_id": pid,
        })
        await client.post("/api/skills", json={"name": "unlinked", "content": "y"})

        resp = await client.get(f"/api/skills?project_id={pid}")
        names = [s["name"] for s in resp.json()]
        assert "linked" in names
        assert "unlinked" not in names


# ── Task-Skill Associations ──


class TestTaskSkillAssociations:
    async def _setup(self, client):
        proj = await client.post("/api/projects", json={"name": "P1"})
        pid = proj.json()["id"]
        task = await client.post("/api/tasks", json={"name": "T1", "project_id": pid})
        tid = task.json()["id"]
        skill = await client.post("/api/skills", json={"name": "extra-skill", "content": "body"})
        sid = skill.json()["id"]
        return pid, tid, sid

    async def test_get_task_skills_empty(self, client):
        pid, tid, _ = await self._setup(client)
        resp = await client.get(f"/api/tasks/{tid}/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_skills"] == []
        assert data["extra_skills"] == []

    async def test_add_and_list_extra_skill(self, client):
        pid, tid, sid = await self._setup(client)

        add_resp = await client.post(f"/api/tasks/{tid}/skills/{sid}")
        assert add_resp.status_code == 200

        list_resp = await client.get(f"/api/tasks/{tid}/skills")
        assert len(list_resp.json()["extra_skills"]) == 1
        assert list_resp.json()["extra_skills"][0]["name"] == "extra-skill"

    async def test_remove_extra_skill(self, client):
        pid, tid, sid = await self._setup(client)

        await client.post(f"/api/tasks/{tid}/skills/{sid}")
        await client.delete(f"/api/tasks/{tid}/skills/{sid}")

        list_resp = await client.get(f"/api/tasks/{tid}/skills")
        assert len(list_resp.json()["extra_skills"]) == 0

    async def test_project_skills_shown_in_task(self, client):
        """Skills linked to the project should appear in task's project_skills."""
        pid, tid, _ = await self._setup(client)
        # Create a project-linked skill
        await client.post("/api/skills", json={
            "name": "proj-skill", "content": "x", "source_type": "project", "source_id": pid,
        })

        list_resp = await client.get(f"/api/tasks/{tid}/skills")
        proj_names = [s["name"] for s in list_resp.json()["project_skills"]]
        assert "proj-skill" in proj_names

    async def test_add_nonexistent_skill(self, client):
        _, tid, _ = await self._setup(client)
        resp = await client.post(f"/api/tasks/{tid}/skills/fake_id")
        assert resp.status_code == 404


# ── Service: get_task_effective_skills ──


class TestEffectiveSkills:
    async def test_union_deduplicates(self, db_session):
        """If a skill is linked to both project and task, it should appear only once."""
        from daiflow.services.skill_service import (
            add_task_skill, get_task_effective_skills, link_skill_to_project,
        )

        p = Project(name="P")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="T", project_id=p.id)
        db_session.add(t)
        s = Skill(source_type="manual", source_id="0", name="shared", content="x")
        db_session.add(s)
        await db_session.flush()

        await link_skill_to_project(db_session, p.id, s.id)
        await add_task_skill(db_session, t.id, s.id)
        await db_session.flush()

        skills = await get_task_effective_skills(db_session, t.id, p.id)
        names = [sk.name for sk in skills]
        assert names.count("shared") == 1

    async def test_combines_project_and_task(self, db_session):
        from daiflow.services.skill_service import (
            add_task_skill, get_task_effective_skills, link_skill_to_project,
        )

        p = Project(name="P")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="T", project_id=p.id)
        db_session.add(t)
        s1 = Skill(source_type="manual", source_id="0", name="proj-only", content="a")
        s2 = Skill(source_type="manual", source_id="0", name="task-only", content="b")
        db_session.add_all([s1, s2])
        await db_session.flush()

        await link_skill_to_project(db_session, p.id, s1.id)
        await add_task_skill(db_session, t.id, s2.id)
        await db_session.flush()

        skills = await get_task_effective_skills(db_session, t.id, p.id)
        names = {sk.name for sk in skills}
        assert names == {"proj-only", "task-only"}


# ── Service: skill_sync ──


class TestSkillSync:
    async def test_assemble_skill_md(self):
        from daiflow.services.skill_sync import assemble_skill_md

        skill = Skill(name="test", description="A test skill", content="# Hello\nWorld")
        md = assemble_skill_md(skill)
        assert md.startswith("---\n")
        assert "name: test\n" in md
        assert "description: A test skill\n" in md
        assert "# Hello\nWorld" in md

    async def test_assemble_quotes_unsafe_yaml(self):
        from daiflow.services.skill_sync import assemble_skill_md

        skill = Skill(name="has:colon", description="line1\nline2", content="body")
        md = assemble_skill_md(skill)
        assert '"has:colon"' in md
        assert '"line1\nline2"' in md

    async def test_parse_roundtrip(self):
        from daiflow.services.skill_sync import assemble_skill_md, parse_skill_md

        skill = Skill(name="round-trip", description="desc", content="# Content\n\nParagraph.")
        md = assemble_skill_md(skill)
        name, desc, body = parse_skill_md(md)
        assert name == "round-trip"
        assert desc == "desc"
        assert "# Content" in body


# ── Service: make_save_skill_tool ──


class TestSaveSkillTool:
    async def test_save_skill_tool_creates(self, db_session):
        from daiflow.services.skill_service import make_save_skill_tool

        p = Project(name="P")
        db_session.add(p)
        await db_session.flush()

        tool = make_save_skill_tool([db_session], p.id)
        result = await tool(None, name="test-tool-skill", description="desc", content="body")
        assert "saved successfully" in result

        # Verify in DB
        from sqlalchemy import select
        row = (await db_session.execute(
            select(Skill).where(Skill.name == "test-tool-skill")
        )).scalar_one()
        assert row.source_type == "project"
        assert row.source_id == p.id

    async def test_save_skill_tool_empty_name(self, db_session):
        from daiflow.services.skill_service import make_save_skill_tool

        p = Project(name="P")
        db_session.add(p)
        await db_session.flush()

        tool = make_save_skill_tool([db_session], p.id)
        result = await tool(None, name="", description="d", content="c")
        assert "Error" in result
