import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
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
import MenuIcon from "@mui/icons-material/Menu";
import CloseIcon from "@mui/icons-material/Close";
import { auth } from "../firebase";
import { useAuth } from "../state/auth";
import { useHeadlinesNav } from "../state/headlinesNav";
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

const menuLinkClass = ({ isActive }: { isActive: boolean }) =>
  `menu-item${isActive ? " active" : ""}`;

export function AppShell() {
  const profile = useAuth((s) => s.profile);
  const isAdmin = profile?.user.role === "admin";
  const headerRef = useRef<HTMLElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  // Mobile hamburger "Topics" section (only on Headlines): the shared tabs.
  const topics = useHeadlinesNav((s) => s.topics);
  const activeTopic = useHeadlinesNav((s) => s.active);
  const setActiveTopic = useHeadlinesNav((s) => s.setActive);
  const onHeadlines =
    location.pathname === "/headlines" || location.pathname === "/";

  // Close the menu on any navigation.
  useEffect(() => setMenuOpen(false), [location.pathname]);

  // Close on Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  // Expose the topbar height so the full-bleed chat + mobile menu sit below it.
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

        {/* Mobile controls — theme toggle next to the hamburger (CSS-gated). */}
        <div className="topbar-mobile">
          <ThemeToggle />
          <button
            className="hamburger"
            onClick={() => setMenuOpen((o) => !o)}
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
          >
            {menuOpen ? <CloseIcon /> : <MenuIcon />}
          </button>
        </div>
      </header>

      {menuOpen && (
        <>
          <div className="menu-backdrop" onClick={() => setMenuOpen(false)} />
          <nav className="mobile-menu" aria-label="Menu">
            <div className="menu-section">
              {NAV.map(({ to, label, Icon }) => (
                <NavLink key={to} to={to} className={menuLinkClass}>
                  <Icon fontSize="small" className="nav-ico" />
                  {label}
                </NavLink>
              ))}
              {isAdmin && (
                <NavLink to="/admin/topics" className={menuLinkClass}>
                  <AdminIcon fontSize="small" className="nav-ico" />
                  Admin
                </NavLink>
              )}
            </div>

            {onHeadlines && topics.length > 0 && (
              <div className="menu-section">
                <div className="menu-label">Topics</div>
                {topics.map((t) => (
                  <button
                    key={t.slug}
                    className={`menu-item${activeTopic === t.slug ? " active" : ""}`}
                    onClick={() => {
                      setActiveTopic(t.slug);
                      setMenuOpen(false);
                    }}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
            )}

            <div className="menu-section">
              <NavLink to="/settings" className={menuLinkClass}>
                <SettingsIcon fontSize="small" className="nav-ico" />
                Settings
              </NavLink>
              <button
                className="menu-item"
                onClick={() => {
                  setMenuOpen(false);
                  signOut(auth);
                }}
              >
                <LogoutIcon fontSize="small" className="nav-ico" />
                Sign out
              </button>
            </div>
          </nav>
        </>
      )}

      <main className="content">
        <Outlet />
      </main>
      <OnboardingTour />
    </div>
  );
}
