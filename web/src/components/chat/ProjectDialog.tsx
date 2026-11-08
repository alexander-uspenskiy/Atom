import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { qk } from "../../api/hooks";
import type { Project } from "../../api/types";
import { errMsg } from "../../lib/format";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { Field } from "../ui/Fields";
import { FolderPicker } from "../ui/FolderPicker";
import { useToast } from "../ui/Toast";

/** Create (project = null) or edit a project: a name plus an optional working folder for its chats. */
export function ProjectDialog({
  open, project, onClose, onSaved, onDelete,
}: { open: boolean; project: Project | null; onClose: () => void; onSaved?: (p: Project) => void; onDelete?: (p: Project) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setName(project?.name ?? "");
      setFolder(project?.folder ?? "");
    }
  }, [open, project]);

  const save = async () => {
    setBusy(true);
    try {
      const body = { name: name.trim(), folder: folder.trim() };
      const p = project ? await api.updateProject(project.id, body) : await api.createProject(body);
      void qc.invalidateQueries({ queryKey: qk.projects });
      toast.success(project ? "Project saved" : "Project created");
      onSaved?.(p);
      onClose();
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={project ? "Edit project" : "New project"}
      footer={
        <>
          {project && onDelete && <Button variant="danger" className="mr-auto" onClick={() => onDelete(project)}>Delete</Button>}
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!name.trim() || busy} onClick={() => void save()}>{project ? "Save" : "Create"}</Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Name" htmlFor="proj-name">
          <input id="proj-name" className="input w-full" value={name} maxLength={80} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && !busy && void save()} />
        </Field>
        <Field label="Project folder" htmlFor="proj-folder" hint="Where the assistant's terminal commands start in this project's chats (needs the terminal enabled in Settings). Empty = the global folder.">
          <FolderPicker id="proj-folder" value={folder} onChange={setFolder} />
        </Field>
      </div>
    </Dialog>
  );
}
