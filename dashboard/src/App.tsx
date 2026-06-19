import { useEffect } from "react";
import { Routes, Route } from "react-router-dom";
import { onAuthStateChanged } from "firebase/auth";
import { auth } from "./firebase";
import { api } from "./api";
import { useAuth } from "./state/auth";
import { useToasts } from "./state/toasts";
import { Toasts } from "./components/Toasts";
import { AppShell } from "./components/AppShell";
import { Login } from "./pages/Login";
import { Headlines } from "./pages/Headlines";
import { Topics } from "./pages/Topics";
import { Settings } from "./pages/Settings";

export default function App() {
  const status = useAuth((s) => s.status);
  const set = useAuth((s) => s.set);
  const push = useToasts((s) => s.push);

  useEffect(() => {
    return onAuthStateChanged(auth, async (user) => {
      if (!user) {
        set({ status: "anon", user: null, profile: null });
        return;
      }
      try {
        const profile = await api.me();
        set({ status: "authed", user, profile });
      } catch {
        push("Signed in, but couldn't reach the bbv2 API.", "error");
        set({ status: "authed", user, profile: null });
      }
    });
  }, [set, push]);

  return (
    <>
      {status === "loading" ? (
        <div className="splash">Loading…</div>
      ) : status === "anon" ? (
        <Login />
      ) : (
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Headlines />} />
            <Route path="topics" element={<Topics />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      )}
      <Toasts />
    </>
  );
}
