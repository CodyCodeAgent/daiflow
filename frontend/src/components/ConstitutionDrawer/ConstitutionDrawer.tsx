import { useState, useEffect } from 'react'
import MarkdownViewer from '../MarkdownViewer/MarkdownViewer'
import { getProject } from '../../api'
import type { TaskData, ProjectData } from '../../api'
import { useLocale } from '../../hooks/useLocale'
import './ConstitutionDrawer.css'

interface TaskInfoDrawerProps {
  task: TaskData
}

export default function TaskInfoDrawer({ task }: TaskInfoDrawerProps) {
  const { t } = useLocale()
  const [open, setOpen] = useState(false)
  const [project, setProject] = useState<ProjectData | null>(null)
  const [projLoading, setProjLoading] = useState(false)
  const [projLoaded, setProjLoaded] = useState(false)

  const handleOpen = () => {
    setOpen(true)
    if (!projLoaded) {
      setProjLoading(true)
      getProject(task.project_id)
        .then(setProject)
        .catch(() => setProject(null))
        .finally(() => { setProjLoading(false); setProjLoaded(true) })
    }
  }

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open])

  return (
    <>
      <button className="constitution-trigger" onClick={handleOpen} title={t('task_info.title')}>
        <span className="constitution-trigger-icon">☰</span>
        <span className="constitution-trigger-label">{t('task_info.button')}</span>
      </button>

      {open && <div className="constitution-backdrop" onClick={() => setOpen(false)} />}

      <div className={`constitution-drawer ${open ? 'open' : ''}`}>
        <div className="constitution-drawer-header">
          <div className="constitution-drawer-title">{t('task_info.title')}</div>
          <button className="constitution-close-btn" onClick={() => setOpen(false)}>✕</button>
        </div>
        <div className="constitution-drawer-body">

          {/* 基本信息 */}
          <div className="task-info-section">
            <div className="task-info-section-title">{t('task_info.section.basic')}</div>
            <div className="task-info-meta-row">
              <span className="task-info-meta-key">{t('task_info.name')}</span>
              <span className="task-info-meta-val">{task.name}</span>
            </div>
            {task.description && (
              <div className="task-info-meta-row">
                <span className="task-info-meta-key">{t('task_info.description')}</span>
                <span className="task-info-meta-val">{task.description}</span>
              </div>
            )}
            <div className="task-info-meta-row">
              <span className="task-info-meta-key">{t('task_info.branch')}</span>
              <code className="task-info-branch">{task.branch}</code>
            </div>
          </div>

          {/* 关联项目 */}
          <div className="task-info-section">
            <div className="task-info-section-title">{t('task_info.section.project')}</div>
            {projLoading ? (
              <div className="task-info-loading">{t('task_info.loading_project')}</div>
            ) : project ? (
              <>
                <div className="task-info-meta-row">
                  <span className="task-info-meta-key">{t('task_info.project_name')}</span>
                  <span className="task-info-meta-val">{project.name}</span>
                </div>
                {(project.repos || []).map((repo, i) => (
                  <div key={i} className="task-info-repo-row">
                    <span className="task-info-repo-type">{repo.repo_type}</span>
                    <div className="task-info-repo-detail">
                      {repo.git_url && <code className="task-info-repo-url">{repo.git_url}</code>}
                      {repo.local_path && <span className="task-info-repo-path">{repo.local_path}</span>}
                    </div>
                  </div>
                ))}
              </>
            ) : null}
          </div>

          {/* PRD */}
          <div className="task-info-section">
            <div className="task-info-section-title">{t('task_info.section.prd')}</div>
            {task.prd
              ? <MarkdownViewer content={task.prd} />
              : <div className="task-info-empty">{t('task_info.no_content')}</div>
            }
          </div>

          {/* 技术方案 */}
          <div className="task-info-section">
            <div className="task-info-section-title">{t('task_info.section.tech_plan')}</div>
            {task.tech_plan
              ? <MarkdownViewer content={task.tech_plan} />
              : <div className="task-info-empty">{t('task_info.no_content')}</div>
            }
          </div>

        </div>
      </div>
    </>
  )
}
