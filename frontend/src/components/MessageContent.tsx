import { useState, type ReactElement } from "react";
import Markdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import "./message-content.css";

function SavedImage({ src, alt }: { src?: string; alt?: string }): ReactElement {
  const [failed, setFailed] = useState(false);
  if (!src || !/^\/bot\/api\/files\/[a-zA-Z0-9_-]+\/download$/.test(src)) {
    return <span className="message-image-unavailable">{alt || "Image"} (preview unavailable)</span>;
  }
  return <span className="message-image">
    {failed ? <span>Image preview unavailable.</span> : <img src={src} alt={alt || "Generated image"} loading="lazy" onError={() => setFailed(true)} />}
    <a href={src} download>Download image</a>
  </span>;
}

/** Raw HTML stays disabled. Only authenticated files can load inline images. */
export function MessageContent({ content }: { content: string }): ReactElement {
  return <div className="message-markdown"><Markdown
    skipHtml
    remarkPlugins={[remarkGfm]}
    urlTransform={(url) => defaultUrlTransform(url)}
    components={{
      a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
      img: ({ src, alt }) => <SavedImage src={typeof src === "string" ? src : undefined} alt={alt} />,
      table: ({ children }) => <div className="message-table-scroll"><table>{children}</table></div>,
    }}
  >{content}</Markdown></div>;
}

