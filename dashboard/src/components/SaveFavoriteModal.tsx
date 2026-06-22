import { useEffect, useState } from "react";
import CloseIcon from "@mui/icons-material/Close";
import StarIcon from "@mui/icons-material/Star";
import { api, type Folder } from "../api";
import { useToasts } from "../state/toasts";

// Pops when a story's ☆ is clicked. Mirrors v1: the link is saved to the default
// "Favorites" folder right away, then you can also file it into an existing or
// brand-new folder. `onSaved` flips the row's star to active.
export function SaveFavoriteModal({
  story,
  onClose,
  onSaved,
}: {
  story: { item_id: string; title: string; url: string };
  onClose: () => void;
  onSaved: () => void;
}) {
  const push = useToasts((s) => s.push);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [folderId, setFolderId] = useState("");
  const [newFolder, setNewFolder] = useState("");
  const [busy, setBusy] = useState(false);

  // On open: ensure it's saved to the default folder, then load folder list.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        await api.addFavorite({
          title: story.title,
          url: story.url,
          item_id: story.item_id,
        });
        onSaved();
        const fs = await api.favoriteFolders();
        if (!alive) return;
        setFolders(fs);
        const def = fs.find((f) => f.name.toLowerCase() === "favorites") ?? fs[0];
        if (def) setFolderId(def.id);
      } catch (e) {
        push(String(e), "error");
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const fileIt = async () => {
    setBusy(true);
    try {
      let fid = folderId;
      const name = newFolder.trim();
      if (name) {
        const created = await api.createFolder(name);
        fid = created.id;
      }
      await api.addFavorite({
        title: story.title,
        url: story.url,
        item_id: story.item_id,
        folder_id: fid,
      });
      onSaved();
      setNewFolder("");
      setFolders(await api.favoriteFolders());
      const target = name || folders.find((f) => f.id === fid)?.name || "folder";
      push(`Saved to ${target}`, "success");
    } catch (e) {
      push(String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Save to favorites"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 className="modal-title">
            <StarIcon fontSize="small" className="modal-star" /> Saved to favorites
          </h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <CloseIcon fontSize="small" />
          </button>
        </div>

        <p className="modal-sub">
          It's in your <strong>Favorites</strong>. File it into a folder if you like.
        </p>

        <label className="field">
          <span>Folder</span>
          <select
            value={folderId}
            onChange={(e) => setFolderId(e.target.value)}
            disabled={busy || folders.length === 0}
          >
            {folders.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name} ({f.count})
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>…or create a new folder</span>
          <input
            type="text"
            value={newFolder}
            placeholder="Folder name"
            maxLength={60}
            onChange={(e) => setNewFolder(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && fileIt()}
          />
        </label>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>
            Done
          </button>
          <button className="btn primary" onClick={fileIt} disabled={busy}>
            {newFolder.trim() ? "Create & add" : "Add to folder"}
          </button>
        </div>
      </div>
    </div>
  );
}
