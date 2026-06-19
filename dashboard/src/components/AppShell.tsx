import { NavLink, Outlet } from "react-router-dom";
import { signOut } from "firebase/auth";
import { auth } from "../firebase";
import { useAuth } from "../state/auth";
import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { to: "/", label: "Headlines", end: true },
  { to: "/topics", label: "Topics", end: false },
  { to: "/settings", label: "Settings", end: false },
];

export function AppShell() {
  const profile = useAuth((s) => s.profile);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◆</span> briefbot
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-right">
          <span className="who">{profile?.user.name}</span>
          <ThemeToggle />
          <button className="btn ghost" onClick={() => signOut(auth)}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
