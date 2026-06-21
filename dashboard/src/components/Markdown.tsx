import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Renders assistant message text as markdown. react-markdown does NOT render raw
// HTML by default (no rehype-raw), so this is safe for model output. Links open in
// a new tab; styling comes from `.md` rules in the stylesheet.
export function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer" />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
