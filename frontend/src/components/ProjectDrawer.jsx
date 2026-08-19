import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { createProject, updateProject } from "../api";
import ProjectForm from "./ProjectForm";

/**
 * Right-side drawer for creating or editing a project. When `project` is
 * provided it runs in edit mode, otherwise it creates a new project.
 *
 * Mutations call the API here and then `onSaved()` so the parent refreshes.
 * Failures rethrow so ProjectForm surfaces an honest inline error.
 */
export default function ProjectDrawer({ project, onClose, onSaved, triggerRef }) {
  const closeBtnRef = useRef(null);

  useEffect(() => {
    closeBtnRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      // Don't swallow Escape meant for an open confirm dialog.
      if (e.key === "Escape" && !document.querySelector(".modal-overlay")) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    return () => {
      triggerRef?.current?.focus?.();
    };
  }, [triggerRef]);

  const submit = async (payload) => {
    if (project) {
      await updateProject(project.id, payload);
    } else {
      await createProject(payload);
    }
    onSaved();
  };

  return (
    <div className="task-drawer-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="task-drawer" role="dialog" aria-modal="true" aria-label={project ? `Edit ${project.name}` : "New project"}>
        <div className="task-drawer__header">
          <h3 className="task-drawer__title">{project ? "Edit project" : "New project"}</h3>
          <button
            ref={closeBtnRef}
            type="button"
            className="task-drawer__icon-btn"
            onClick={onClose}
            aria-label="Close project form"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="task-drawer__body">
          <ProjectForm
            initial={project}
            submitLabel={project ? "Save changes" : "Create Project"}
            onSave={submit}
            onCancel={onClose}
          />
        </div>
      </div>
    </div>
  );
}