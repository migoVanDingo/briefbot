import { useEffect, useState } from "react";
import { api, type Settings as S } from "../api";
import { useToasts } from "../state/toasts";

export function Settings() {
  const push = useToasts((s) => s.push);
  const [settings, setSettings] = useState<S | null>(null);
  const [saving, setSaving] = useState(false);

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
      <h1 className="page-title">Settings</h1>
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

        <button className="btn primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
