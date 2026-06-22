import { useEffect, useState } from "react";
import SettingsIcon from "@mui/icons-material/SettingsOutlined";
import SaveIcon from "@mui/icons-material/SaveOutlined";
import ReplayIcon from "@mui/icons-material/ReplayOutlined";
import { api, type Settings as S } from "../api";
import { useAuth } from "../state/auth";
import { useToasts } from "../state/toasts";

// Tutorial flags reset by "Replay tutorials" (the per-page tours + the global
// onboarding walkthrough). Mirrors the server-side ALLOWED_FLAGS.
const TUTORIAL_FLAGS = [
  "onboarding_done",
  "tour:headlines",
  "tour:stories",
  "tour:topics",
  "tour:favorites",
];

export function Settings() {
  const push = useToasts((s) => s.push);
  const clearFlag = useAuth((s) => s.clearFlag);
  const [settings, setSettings] = useState<S | null>(null);
  const [saving, setSaving] = useState(false);

  const replayTutorials = () => {
    TUTORIAL_FLAGS.forEach(clearFlag);
    push("Tutorials will replay on your next visit to each page.", "success");
  };

  useEffect(() => {
    api
      .getSettings()
      .then(setSettings)
      .catch((e) => push(String(e), "error"));
  }, [push]);

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      await api.putSettings(settings);
      push("Settings saved", "success");
    } catch (e) {
      push(String(e), "error");
    } finally {
      setSaving(false);
    }
  };

  if (!settings) return <div className="muted pad">Loading…</div>;

  return (
    <div className="page narrow">
      <h1 className="page-title">
        <SettingsIcon className="title-ico" /> Settings
      </h1>
      <div className="card form">
        <label className="check">
          <input
            type="checkbox"
            checked={settings.email_enabled}
            onChange={(e) =>
              setSettings({ ...settings, email_enabled: e.target.checked })
            }
          />
          <span>Email me a digest</span>
        </label>

        <label className="field">
          <span>Digest size (items)</span>
          <input
            type="number"
            min={1}
            max={100}
            value={settings.digest_limit}
            onChange={(e) =>
              setSettings({
                ...settings,
                digest_limit: Number(e.target.value) || 1,
              })
            }
          />
        </label>

        <button
          className="btn primary icon-btn-text"
          onClick={save}
          disabled={saving}
        >
          <SaveIcon fontSize="small" />
          {saving ? "Saving…" : "Save"}
        </button>
      </div>

      <div className="card form">
        <label className="field">
          <span>Tutorials</span>
          <button
            className="btn ghost icon-btn-text"
            onClick={replayTutorials}
            type="button"
          >
            <ReplayIcon fontSize="small" />
            Replay tutorials
          </button>
        </label>
      </div>
    </div>
  );
}
