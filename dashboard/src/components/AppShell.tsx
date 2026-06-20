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

const NAV = [
  { to: "/headlines", label: "Headlines", Icon: ArticleIcon },
  { to: "/chat", label: "Chat", Icon: ChatIcon },
  { to: "/stories", label: "Stories", Icon: FeedIcon },
  { to: "/favorites", label: "Favorites", Icon: StarIcon },
  { to: "/topics", label: "Topics", Icon: TopicIcon },
];

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `nav-link${isActive ? " active" : ""}`;

export function AppShell() {
  const profile = useAuth((s) => s.profile);
  const isAdmin = profile?.user.role === "admin";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <AutoAwesomeIcon className="brand-mark" fontSize="small" /> briefbot
        </div>
        <nav className="nav">
          {NAV.map(({ to, label, Icon }) => (
            <NavLink key={to} to={to} className={linkClass}>
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
    </div>
  );
}
