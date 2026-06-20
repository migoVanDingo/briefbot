import { useEffect } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { onAuthStateChanged } from "firebase/auth";
import { auth } from "./firebase";
import { api } from "./api";
import { useAuth } from "./state/auth";
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
import { Settings } from "./pages/Settings";

// Gate the admin area: non-admins are redirected to Headlines. (Enforcement is
// on the backend via require_admin; this just hides the unreachable UI.)
function RequireAdmin({ children }: { children: JSX.Element }) {
  const role = useAuth((s) => s.profile?.user.role);
  return role === "admin" ? children : <Navigate to="/headlines" replace />;
}

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
          </Route>
        </Routes>
      )}
      <Toasts />
    </>
  );
}
