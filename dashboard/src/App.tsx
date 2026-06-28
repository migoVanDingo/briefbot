import { useEffect } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { onAuthStateChanged } from "firebase/auth";
import { auth } from "./firebase";
import { api } from "./api";
import { useAuth } from "./state/auth";
import { useThemeStore } from "./state/themeStore";
import { useToasts } from "./state/toasts";
import { Toasts } from "./components/Toasts";
import { AppShell } from "./components/AppShell";
import { Login } from "./pages/Login";
import { Headlines } from "./pages/Headlines";
import { Chat } from "./pages/Chat";
import { Stories } from "./pages/Stories";
import { Favorites } from "./pages/Favorites";
import { TopicsHome } from "./pages/TopicsHome";
import { Topics } from "./pages/admin/Topics";
import { TopicDetail } from "./pages/admin/TopicDetail";
import { Scheduling } from "./pages/admin/Scheduling";
import { Metrics } from "./pages/admin/Metrics";
import { Settings } from "./pages/Settings";

// Gate the admin area: users without the admin capability are redirected to
// Headlines. (Enforcement is on the backend; this just hides the unreachable UI.)
function RequireAdmin({ children }: { children: JSX.Element }) {
  const caps = useAuth((s) => s.profile?.user.capabilities);
  const ok = !!caps && (caps.includes("*") || caps.includes("admin:read"));
  return ok ? children : <Navigate to="/headlines" replace />;
}

export default function App() {
  const status = useAuth((s) => s.status);
  const set = useAuth((s) => s.set);
  const hydrateTheme = useThemeStore((s) => s.hydrate);
  const push = useToasts((s) => s.push);

  useEffect(() => {
    return onAuthStateChanged(auth, async (user) => {
      if (!user) {
        set({ status: "anon", user: null, profile: null });
        return;
      }
      try {
        await api.exchange(); // Firebase token → bbv2 session cookie (0019)
        const profile = await api.me();
        set({ status: "authed", user, profile });
        hydrateTheme(profile.preferences.theme); // DB theme wins over the cache
      } catch {
        push("Signed in, but couldn't reach the bbv2 API.", "error");
        set({ status: "authed", user, profile: null });
      }
    });
  }, [set, push, hydrateTheme]);

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
            <Route path="headlines" element={<Headlines />} />
            <Route path="chat" element={<Chat />} />
            <Route path="stories" element={<Stories />} />
            <Route path="favorites" element={<Favorites />} />
            <Route path="topics" element={<TopicsHome />} />
            <Route path="settings" element={<Settings />} />
            {/* Admin — source curation, gated to admins (backend enforces 403) */}
            <Route
              path="admin/topics"
              element={
                <RequireAdmin>
                  <Topics />
                </RequireAdmin>
              }
            />
            <Route
              path="admin/topics/:slug"
              element={
                <RequireAdmin>
                  <TopicDetail />
                </RequireAdmin>
              }
            />
            <Route
              path="admin/scheduling"
              element={
                <RequireAdmin>
                  <Scheduling />
                </RequireAdmin>
              }
            />
            <Route
              path="admin/metrics"
              element={
                <RequireAdmin>
                  <Metrics />
                </RequireAdmin>
              }
            />
          </Route>
        </Routes>
      )}
      <Toasts />
    </>
  );
}
