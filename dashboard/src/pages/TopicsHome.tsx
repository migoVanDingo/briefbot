// Stub — the user-facing topic flow (/topics) is built in a later plan:
// create a topic → sources auto-discover & approve → collect → subscribe.
// (Source curation lives in the admin area at /admin/topics for now.)
export function TopicsHome() {
  return (
    <div className="page">
      <h1 className="page-title">Topics</h1>
      <div className="empty">
        <h2>Coming soon</h2>
        <p className="muted">
          Create a topic and we'll discover sources, gather stories, and let you
          subscribe — no setup required.
        </p>
      </div>
    </div>
  );
}
