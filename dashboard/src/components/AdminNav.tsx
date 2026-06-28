import { NavLink } from "react-router-dom";
import TopicIcon from "@mui/icons-material/TagOutlined";
import ScheduleIcon from "@mui/icons-material/ScheduleOutlined";
import InsightsIcon from "@mui/icons-material/InsightsOutlined";

// Sub-navigation for the owner/admin area.
const TABS = [
  { to: "/admin/topics", label: "Topics", Icon: TopicIcon },
  { to: "/admin/scheduling", label: "Scheduling", Icon: ScheduleIcon },
  { to: "/admin/metrics", label: "Metrics", Icon: InsightsIcon },
];

export function AdminNav() {
  return (
    <nav className="admin-nav">
      {TABS.map(({ to, label, Icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) => `admin-tab${isActive ? " active" : ""}`}
        >
          <Icon fontSize="small" className="nav-ico" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
