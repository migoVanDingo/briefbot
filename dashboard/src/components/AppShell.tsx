import { useEffect, useRef } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { signOut } from "firebase/auth";
import ArticleIcon from "@mui/icons-material/ArticleOutlined";
import ChatIcon from "@mui/icons-material/ChatBubbleOutlineOutlined";
import FeedIcon from "@mui/icons-material/FeedOutlined";
import StarIcon from "@mui/icons-material/StarBorder";
import TopicIcon from "@mui/icons-material/TagOutlined";
import AdminIcon from "@mui/icons-material/AdminPanelSettingsOutlined";
import SettingsIcon from "@mui/icons-material/SettingsOutlined";
import LogoutIcon from "@mui/icons-material/LogoutOutlined";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import { auth } from "../firebase";
import { useAuth } from "../state/auth";
import { ThemeToggle } from "./ThemeToggle";
import { OnboardingTour } from "./OnboardingTour";

const NAV = [
  { to: "/headlines", label: "Headlines", Icon: ArticleIcon, tour: "headlines" },
  { to: "/stories", label: "Stories", Icon: FeedIcon, tour: "stories" },
  { to: "/topics", label: "Topics", Icon: TopicIcon, tour: "topics" },
  { to: "/chat", label: "Chat", Icon: ChatIcon, tour: "chat" },
  { to: "/favorites", label: "Favorites", Icon: StarIcon, tour: "favorites" },
];

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `nav-link${isActive ? " active" : ""}`;

export function AppShell() {
  const profile = useAuth((s) => s.profile);
  const isAdmin = profile?.user.role === "admin";
  const headerRef = useRef<HTMLElement>(null);

  // Expose the topbar height so the full-bleed chat can sit right below it.
  useEffect(() => {
    const el = headerRef.current;
    if (!el) return;
    const set = () =>
      document.documentElement.style.setProperty("--topbar-h", `${el.offsetHeight}px`);
    set();
    const ro = new ResizeObserver(set);
    ro.observe(el);
    window.addEventListener("resize", set);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", set);
    };
  }, []);

  return (
    <div className="app">
      <header className="topbar" ref={headerRef}>
        <div className="brand">
          <AutoAwesomeIcon className="brand-mark" fontSize="small" /> briefbot
        </div>
        <nav className="nav">
          {NAV.map(({ to, label, Icon, tour }) => (
            <NavLink key={to} to={to} className={linkClass} data-tour={tour}>
              <Icon fontSize="small" className="nav-ico" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-right">
          {isAdmin && (
            <NavLink to="/admin/topics" className={linkClass}>
              <AdminIcon fontSize="small" className="nav-ico" />
              Admin
            </NavLink>
          )}
          <NavLink to="/settings" className={linkClass}>
            <SettingsIcon fontSize="small" className="nav-ico" />
            Settings
          </NavLink>
          <span className="who">{profile?.user.name}</span>
          <ThemeToggle />
          <button className="btn ghost icon-btn-text" onClick={() => signOut(auth)}>
            <LogoutIcon fontSize="small" />
            Sign out
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
      <OnboardingTour />
    </div>
  );
}
