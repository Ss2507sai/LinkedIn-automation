import { useState, useEffect } from "react";

const FIVETRAN_PLAYBOOK = `OPENER SELECTION - pick the single best one based on profile signals:
O1: FinOps Crisis - CTOs, FinOps, agency/multi-client roles. Signals: Fivetran mentioned, cost optimization, connection costs. Hook: Have you modeled Fivetran shift to connection-level tiering? Pain: MAR inflation, $5/connection minimums, deleted row billing.
O2: Salesforce Standoff - Enterprise Architects, VP IT, Salesforce-heavy orgs. Signals: Salesforce, CRM pipelines, compliance, enterprise architecture. Hook: How are you mitigating the Fivetran/Salesforce AppExchange dispute? Pain: API fees up to 8x, pipeline breakage risk.
O3: AI Velocity Bottleneck - CDO, VP Eng, Head of AI, ML leaders. Signals: AI/ML, GenAI, RAG, vector DBs, feature stores. Hook: Are data engineering backlogs slowing your AI/ML deployments? Pain: Batch ELT overwrites state, AI needs streaming and historical replay. DEFAULT for most data leaders.
O4: Triple Tax - Data Engineers, Analytics Engineers. Signals: dbt, Snowflake, transformation costs, data modeling. Hook: Are you paying Snowflake for compute, Fivetran for orchestration, and dbt for modeling? Pain: Triple charging for one transformation.
O5: Fear of Breakage - Data Engineers, Head of Data, complex pipeline teams. Signals: BI dashboards, downstream dependencies, rigid pipelines. Hook: Can data scientists test new models without risking BI dashboards? Pain: Point-to-point ELT breaks downstream on any change.
RULES: If AI/ML/GenAI present use O3. If Fivetran explicit use O1 or O4. If Salesforce-heavy use O2. If dbt/Snowflake stack use O4. If complex pipelines/BI use O5. Default is O3.`;

const SYSTEM_PROMPT = `You are helping Sai Shankar Tamminaina run LinkedIn outreach for Matterbeam - a Boston-based data infrastructure startup. Matterbeam is Git for data - an immutable time-ordered log enabling deterministic point-in-time replay of any dataset without pipeline rebuilds. CEO is Michael, Head of Solutions Engineering is Alex Jackson.

${FIVETRAN_PLAYBOOK}

DECISION FRAMEWORK:
- VP/Director/Head/C-suite: full 4-component system
- IC/Manager at large company: champion-first, ask for intro to data leader  
- IC/Manager at small company: pain-first DM, no comment
- Original post under 2 weeks: comment first, DM next day
- Post over 1 month OR repost: skip comment, go straight to DM
- Weak ICP: referral angle only

COMMENT RULES:
- Only comment on genuine insight/opinion posts that end with a thought or question NOT a product link or CTA
- NEVER comment on promotional posts, job announcements, product launches, event announcements, certification posts
- NEVER connect comment to data, pipelines, infrastructure, versioning, or Matterbeam even indirectly
- Max 50 words, no questions, peer observation only
- If no qualifying post: write exactly "Skip - no qualifying original post. Go straight to DM."

INITIAL DM GOLD STANDARD - match this style exactly:
"Hey Swapnil, Thanks for connecting! Running Glue into both Redshift and Snowflake means your transformation logic lives in two places - and backfilling historical data into one after its already been processed in the other is where teams usually hit a wall. We're building Matterbeam (data versioning for AI systems) with my CEO Michael in Boston. When Snowflake needs data that Redshift already processed last month, can you replay that exact pipeline state without rebuilding from scratch? Best, Sai"
WHY IT WORKS: Names friction without explaining it. No product pitch before question. Scenario question specific and impossible to ignore. Under 90 words. Reads like a peer.

RULES: Under 90 words. No em dashes. No bullets. No product pitch before question. No explaining stack back to them. No competitor names (Fivetran/Snowflake/dbt/Databricks etc).

PRODUCE EXACTLY THIS OUTPUT:

**DECISION:** [seniority] at [company]. [Post status]. Opener: [O number and name]. Why: [1-2 sentences on which signals triggered this opener].

---

**1. COMMENT**
POST TO COMMENT ON: [exact post first line or Skip]
[comment or Skip message]

---

**2. INITIAL DM**
[Full DM]

---

**3. FOLLOW-UP DM**
Hey [Name],

Quick follow-up on my earlier message - curious if you had a chance to think about it?

I'm genuinely interested in learning [specific technical challenge tied to their work and opener].

Would love 15-20 mins to exchange notes. Learning from people like you genuinely helps us build the right thing.

Here's our calendar: https://app.apollo.io/#/meet/vde-uj0-nj8/30-min

Best,
Sai

---

**4. CONTEXT NOTE**
NAME: [name]
TITLE & COMPANY: [role and company]
BACKGROUND: [key achievements]
ICP STRENGTH: [Strong/Medium/Weak] - [reason]
OPENER USED: [O number, name, hook line]
MATTERBEAM FIT: [specific pain tied to opener]
APPROACH: [method used]
BEST ANGLE: [strongest hook]
NEXT STEP: [what to dig into when they respond]`;

const VALIDATOR_PROMPT = `You are a strict validator for Matterbeam LinkedIn outreach. Fix any section that violates these rules. Keep compliant sections unchanged.

COMMENT: Max 50 words. No questions. No Matterbeam or product mentions. Peer observation only.
DISQUALIFY and write "Skip - promotional post. Go straight to DM." if post contains: "explore what we built", "ezorro", "check it out", "visit our", "link in comments", "register here", "excited to announce", "thrilled to share", "congrats", "new role", "joining", "promoted", "starting a new position", "earned", "certified", "happy to share", "proud to share".
If no qualifying post write exactly: Skip - no qualifying original post. Go straight to DM.
NEVER connect comment to data, pipelines, infrastructure, versioning, or anything Matterbeam-related.

INITIAL DM: Must start "Hey [Name]," blank line "Thanks for connecting!" blank line 1-2 sentences naming friction (peer tone, actual tools, NO competitor names) blank line "We're building Matterbeam (data versioning for AI systems) with my CEO Michael in Boston." then ONE scenario question "When [specific scenario], can you [specific capability]?" blank line "Best," "Sai". Max 90 words. No em dashes. No bullets.

FOLLOW-UP DM: "Hey [Name]," then quick follow-up line, learning interest line, 15-20 mins exchange line, calendar https://app.apollo.io/#/meet/vde-uj0-nj8/30-min, Best, Sai. Max 70 words. No em dashes.

Return the full corrected output in identical section format. No commentary.`;

const DISQUALIFY_TERMS = [
  "explore what we built", "check it out", "ezorro", "visit our", "link in comments",
  "register here", "follow our page", "excited to announce", "thrilled to share",
  "congrats on", "new role", "joining us", "promoted to", "starting a new position",
  "happy to share that i", "proud to share", "i'm excited", "check out what we",
  "learn more at", "sign up here", "register now", "earned the", "certified",
  "passed the", "completed the course", "exhibiting at", "speaking at", "see you there"
];

const filterPosts = (rawPosts) => {
  if (!rawPosts.trim()) return "No posts provided";
  const blocks = rawPosts
    .split(/\n{3,}|(?=Feed post number|\d+w\s+•|\d+mo\s+•|\d+d\s+•|\d+h\s+•)/g)
    .map(p => p.trim())
    .filter(p => p.length > 80);
  const qualified = blocks.filter(post => {
    const lower = post.toLowerCase();
    return !DISQUALIFY_TERMS.some(term => lower.includes(term));
  });
  if (qualified.length === 0) return "NO_QUALIFYING_POSTS";
  return "QUALIFYING POSTS (already filtered - pick best under 2 weeks old):\n\n" + qualified.slice(0, 5).join("\n\n---\n\n");
};

export default function App() {
  const [profile, setProfile] = useState("");
  const [posts, setPosts] = useState("");
  const [result, setResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");
  const [history, setHistory] = useState([]);
  const [view, setView] = useState("generator");
  const [selectedHistory, setSelectedHistory] = useState(null);
  const [replyInput, setReplyInput] = useState("");
  const [replyResult, setReplyResult] = useState("");
  const [replyLoading, setReplyLoading] = useState(false);
  const [critique, setCritique] = useState("");
  const [critiqueLoading, setCritiqueLoading] = useState(false);

  useEffect(() => {
    try {
      const v7 = localStorage.getItem("mb_v7");
      const v6 = localStorage.getItem("mb_v6");
      const data = v7 || v6;
      if (data) {
        setHistory(JSON.parse(data));
        if (!v7 && v6) localStorage.setItem("mb_v7", v6);
      }
    } catch (e) {}
  }, []);

  const callAPI = async (system, userMsg, maxTokens) => {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "anthropic-dangerous-direct-browser-access": "true"
      },
      body: JSON.stringify({
        model: "claude-sonnet-4-20250514",
        max_tokens: maxTokens || 1500,
        system,
        messages: [{ role: "user", content: userMsg }]
      })
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error.message);
    if (data.content && data.content[0] && data.content[0].text) return data.content[0].text;
    throw new Error("No content returned");
  };

  const extractName = (profileText, resultText) => {
    const contextMatch = resultText.match(/NAME:\s*([^\n]+)/);
    const profileMatch = profileText.match(/^([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+){1,3})/m);
    return contextMatch ? contextMatch[1].trim() : profileMatch ? profileMatch[1].trim() : "Unknown";
  };

  const saveToHistory = (profileText, resultText) => {
    const name = extractName(profileText, resultText);
    const decisionMatch = resultText.match(/\*\*DECISION:\*\*(.*?)---/s);
    const decision = decisionMatch ? decisionMatch[1].trim().substring(0, 80) : "";
    const existingIndex = history.findIndex(h => h.name.toLowerCase().trim() === name.toLowerCase().trim());
    if (existingIndex !== -1) {
      const updated = [...history];
      updated[existingIndex] = { ...updated[existingIndex], result: resultText, decision, profile: profileText, date: new Date().toLocaleDateString() };
      setHistory(updated);
      try { localStorage.setItem("mb_v7", JSON.stringify(updated)); } catch (e) {}
      return;
    }
    const entry = { id: Date.now(), name, decision, profile: profileText, result: resultText, date: new Date().toLocaleDateString(), status: "Pending", conversation: [] };
    const updated = [entry, ...history].slice(0, 100);
    setHistory(updated);
    try { localStorage.setItem("mb_v7", JSON.stringify(updated)); } catch (e) {}
  };

  const updateHistory = (id, changes) => {
    const updated = history.map(h => h.id === id ? { ...h, ...changes } : h);
    setHistory(updated);
    if (selectedHistory && selectedHistory.id === id) setSelectedHistory(prev => ({ ...prev, ...changes }));
    try { localStorage.setItem("mb_v7", JSON.stringify(updated)); } catch (e) {}
  };

  const analyze = async () => {
    if (!profile.trim()) return;
    setLoading(true);
    setError("");
    setResult("");
    setCritique("");
    try {
      setLoadingMsg("Filtering posts...");
      const filteredPosts = filterPosts(posts);
      const postsSection = filteredPosts === "NO_QUALIFYING_POSTS"
        ? "POSTS: All posts were promotional. Skip comment - go straight to DM."
        : "POSTS:\n" + filteredPosts;

      setLoadingMsg("Analyzing profile...");
      const raw = await callAPI(SYSTEM_PROMPT, "Analyze this LinkedIn profile and posts, then generate all 4 outreach components:\n\nPROFILE:\n" + profile + "\n\n" + postsSection, 1800);

      setLoadingMsg("Validating messages...");
      const validated = await callAPI(VALIDATOR_PROMPT, "Fix this outreach output to match all rules exactly:\n\n" + raw, 1000);

      const secs = parseResult(validated);
      const commentSec = secs.find(s => s.id === "comment");
      let finalResult = validated;
      if (commentSec) {
        const productTerms = ["replay", "versioning", "pipeline", "data layer", "snapshot", "point-in-time", "immutable", "lineage", "matterbeam", "deterministic", "data architecture", "data infrastructure", "infrastructure breaks"];
        const hasProductTerm = productTerms.some(term => commentSec.content.toLowerCase().includes(term));
        if (hasProductTerm) {
          finalResult = validated.replace(commentSec.content, "POST TO COMMENT ON: Skip\nSkip - comment contained product language. Go straight to DM.");
        }
      }
      setResult(finalResult);
      saveToHistory(profile, finalResult);
    } catch (e) {
      setError(e.message || "Something went wrong. Try again.");
    }
    setLoading(false);
    setLoadingMsg("");
  };

  const getCritique = async () => {
    if (!result) return;
    setCritiqueLoading(true);
    setCritique("");
    try {
      const text = await callAPI(
        "You are a top 1% SDR coach reviewing LinkedIn outreach for Matterbeam. Be direct and specific. No fluff.",
        "Review this outreach and give specific improvements. Focus on: Is the comment too product-adjacent? Is the DM observation sharp enough? Is the question specific and impossible to ignore? Is anything too long?\n\nOutreach:\n" + result + "\n\nFormat:\n**WHAT WORKS:**\n[1-2 lines]\n\n**IMPROVE:**\n[2-3 specific suggestions with examples]\n\n**STRONGER QUESTION:**\n[Rewrite just the discovery question if it can be sharper]",
        600
      );
      setCritique(text);
    } catch (e) {
      setCritique("Error. Please try again.");
    }
    setCritiqueLoading(false);
  };

  const handleReply = async (entry) => {
    if (!replyInput.trim()) return;
    setReplyLoading(true);
    setReplyResult("");
    const secs = parseResult(entry.result);
    const ctx = (secs.find(s => s.id === "context") || {}).content || "";
    const conv = entry.conversation || [];
    const prev = conv.map(c => c.from + ": " + c.text).join("\n");
    const saiMessages = conv.filter(c => c.from === "Sai").length;
    const level = saiMessages === 0 ? 1 : saiMessages === 1 ? 2 : saiMessages >= 2 ? 3 : 1;

    const levelRules = "FOLLOW-UP LEVEL: " + level + ". Sai sent " + saiMessages + " messages.\n" +
      "L1 no reply: Soft bump, binary question, under 40 words, no calendar.\n" +
      "L2 still no reply: Pattern interrupt, fresh angle, under 35 words, no calendar.\n" +
      "L3 still no reply: Graceful exit, remove pressure, under 30 words, include calendar.\n" +
      "L4+: Output STOP - tell Sai to move to No Response and stop messaging.\n" +
      "If prospect REPLIED: acknowledge their specific tool/method, name exact gap, one Matterbeam line, clean meeting ask with Alex our Head of Solutions Engineering and calendar.";

    const prompt = "Prospect context:\n" + ctx + "\n\nConversation:\n" + prev + "\n\nLatest input:\n" + replyInput + "\n\n" + levelRules + "\n\nCalendar: https://app.apollo.io/#/meet/vde-uj0-nj8/30-min\n\n**STAGE:** [Cold/Engaged/Pain described/Pain confirmed/Ready to book/STOP]\n**ANALYSIS:** [1-2 sentences]\n**NEXT MESSAGE:**\n[message]";
    try {
      const text = await callAPI(
        "You are a top 1% SDR for Matterbeam. Michael is CEO. Alex Jackson is Head of Solutions Engineering. Direct, peer-to-peer, no em dashes, no bullets. Follow level rules exactly.",
        prompt, 600
      );
      setReplyResult(text);
      updateHistory(entry.id, { conversation: conv.concat([{ from: "Them", text: replyInput }]) });
      setReplyInput("");
    } catch (e) {
      setReplyResult("Error. Please try again.");
    }
    setReplyLoading(false);
  };

  const saveReplyToConvo = (entry, replyText) => {
    const msgMatch = replyText.match(/\*\*NEXT MESSAGE:\*\*\n([\s\S]+)/);
    const msg = msgMatch ? msgMatch[1].trim() : replyText;
    updateHistory(entry.id, { conversation: (entry.conversation || []).concat([{ from: "Sai", text: msg }]) });
    setReplyResult("");
  };

  const copyText = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(""), 2000);
  };

  const parseResult = (text) => {
    if (!text) return [];
    const sections = [];
    const parts = text.split("---").map(p => p.trim()).filter(Boolean);
    parts.forEach(part => {
      if (part.startsWith("**DECISION:**")) sections.push({ id: "decision", label: "Decision", content: part.replace("**DECISION:**", "").trim() });
      else if (part.includes("**1. COMMENT**")) sections.push({ id: "comment", label: "Comment", content: part.replace("**1. COMMENT**", "").trim() });
      else if (part.includes("**2. INITIAL DM**")) sections.push({ id: "dm", label: "Initial DM", content: part.replace("**2. INITIAL DM**", "").trim() });
      else if (part.includes("**3. FOLLOW-UP DM**")) sections.push({ id: "followup", label: "Follow-Up DM", content: part.replace("**3. FOLLOW-UP DM**", "").trim() });
      else if (part.includes("**4. CONTEXT NOTE**")) sections.push({ id: "context", label: "Context Note", content: part.replace("**4. CONTEXT NOTE**", "").trim() });
    });
    return sections;
  };

  const parseReply = (text) => {
    const stage = ((text.match(/\*\*STAGE:\*\*\s*([^\n]+)/) || [])[1] || "").trim();
    const analysis = ((text.match(/\*\*ANALYSIS:\*\*\s*([\s\S]+?)\*\*NEXT MESSAGE:\*\*/) || [])[1] || "").trim();
    const message = ((text.match(/\*\*NEXT MESSAGE:\*\*\n([\s\S]+)/) || [])[1] || text).trim();
    return { stage, analysis, message };
  };

  const downloadCSV = () => {
    if (!history.length) return;
    const headers = ["Name","Date","Status","Decision","Comment","Initial DM","Follow-Up DM","Context Note"];
    const rows = history.map(h => {
      const secs = parseResult(h.result);
      const get = id => ((secs.find(s => s.id === id) || {}).content || "").replace(/"/g, '""');
      return ['"'+h.name+'"','"'+h.date+'"','"'+h.status+'"','"'+get("decision")+'"','"'+get("comment")+'"','"'+get("dm")+'"','"'+get("followup")+'"','"'+get("context")+'"'].join(",");
    });
    const blob = new Blob([[headers.join(","), ...rows].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "matterbeam_" + new Date().toISOString().slice(0,10) + ".csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const C = {
    decision: { bg: "#f0f9ff", border: "#0ea5e9", label: "#0369a1" },
    comment: { bg: "#f0fdf4", border: "#22c55e", label: "#15803d" },
    dm: { bg: "#faf5ff", border: "#a855f7", label: "#7e22ce" },
    followup: { bg: "#fff7ed", border: "#f97316", label: "#c2410c" },
    context: { bg: "#fefce8", border: "#eab308", label: "#854d0e" }
  };

  const SC = { "Pending":"#94a3b8","Comment sent":"#22c55e","DM sent":"#a855f7","Follow-up sent":"#f97316","Meeting booked":"#0ea5e9","No response":"#ef4444" };
  const GC = { "Cold":"#94a3b8","Engaged":"#22c55e","Pain described":"#f97316","Pain confirmed":"#a855f7","Ready to book":"#0ea5e9" };

  const stats = {
    total: history.length,
    dms: history.filter(h => h.status === "DM sent" || h.status === "Follow-up sent").length,
    booked: history.filter(h => h.status === "Meeting booked").length,
    rate: history.length ? Math.round(history.filter(h => h.status === "Meeting booked").length / history.length * 100) + "%" : "0%"
  };

  const sections = parseResult(result);

  const SectionCard = ({ sec }) => {
    const c = C[sec.id] || { bg: "#f8fafc", border: "#94a3b8", label: "#475569" };
    let postLabel = null;
    let commentText = sec.content;
    if (sec.id === "comment" && sec.content.includes("POST TO COMMENT ON:")) {
      const lines = sec.content.split("\n");
      const postLine = lines.find(l => l.startsWith("POST TO COMMENT ON:"));
      postLabel = postLine ? postLine.replace("POST TO COMMENT ON:", "").trim() : null;
      commentText = lines.filter(l => !l.startsWith("POST TO COMMENT ON:")).join("\n").trim();
    }
    return (
      <div style={{ background: c.bg, border: `1.5px solid ${c.border}`, borderRadius: 12, padding: 18, marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <span style={{ fontWeight: 700, fontSize: 11, color: c.label, textTransform: "uppercase", letterSpacing: "0.07em" }}>{sec.label}</span>
          {sec.id !== "decision" && (
            <button onClick={() => copyText(commentText || sec.content, sec.id)} style={{ fontSize: 12, padding: "4px 14px", borderRadius: 6, border: `1px solid ${c.border}`, background: "#fff", color: c.label, cursor: "pointer", fontWeight: 600 }}>
              {copied === sec.id ? "Copied!" : "Copy"}
            </button>
          )}
        </div>
        {postLabel && (
          <div style={{ background: "#fff", border: "1px dashed #94a3b8", borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>Find this post on their profile</div>
            <div style={{ fontSize: 12, color: "#475569", fontStyle: "italic" }}>"{postLabel}"</div>
          </div>
        )}
        <div style={{ fontSize: 13, color: "#1e293b", lineHeight: 1.75, whiteSpace: "pre-wrap" }}>{commentText}</div>
      </div>
    );
  };

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 820, margin: "0 auto", padding: "20px 16px", background: "#f8fafc", minHeight: "100vh" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: "#0f172a" }}>Matterbeam Outreach</div>
          <div style={{ fontSize: 12, color: "#64748b" }}>LinkedIn Outreach Generator v7</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {history.length > 0 && <button onClick={downloadCSV} style={{ padding: "7px 16px", borderRadius: 8, border: "1px solid #22c55e", background: "#f0fdf4", color: "#15803d", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>Export CSV</button>}
          {["generator","history"].map(v => (
            <button key={v} onClick={() => setView(v)} style={{ padding: "7px 16px", borderRadius: 8, border: "none", background: view === v ? "#0f172a" : "#e2e8f0", color: view === v ? "#fff" : "#475569", fontWeight: 600, fontSize: 13, cursor: "pointer", textTransform: "capitalize" }}>
              {v === "history" ? "History (" + history.length + ")" : "Generator"}
            </button>
          ))}
        </div>
      </div>

      {history.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 20 }}>
          {[["Total", stats.total, "#0f172a"],["DMs Sent", stats.dms, "#a855f7"],["Meetings", stats.booked, "#0ea5e9"],["Booking Rate", stats.rate, "#22c55e"]].map(([label, value, color]) => (
            <div key={label} style={{ background: "#fff", borderRadius: 10, padding: "12px 16px", textAlign: "center", boxShadow: "0 1px 2px rgba(0,0,0,0.06)" }}>
              <div style={{ fontSize: 20, fontWeight: 700, color }}>{value}</div>
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {view === "generator" && (
        <>
          <div style={{ background: "#fff", borderRadius: 12, padding: 20, boxShadow: "0 1px 3px rgba(0,0,0,0.08)", marginBottom: 20 }}>
            <label style={{ fontWeight: 600, fontSize: 14, color: "#374151", display: "block", marginBottom: 8 }}>Paste LinkedIn Profile</label>
            <textarea value={profile} onChange={e => setProfile(e.target.value)} placeholder="Paste the full LinkedIn profile text here..." style={{ width: "100%", height: 120, padding: 12, borderRadius: 8, border: "1.5px solid #e2e8f0", fontSize: 13, resize: "vertical", outline: "none", boxSizing: "border-box", color: "#1e293b" }} />
            <label style={{ fontWeight: 600, fontSize: 14, color: "#374151", display: "block", marginTop: 16, marginBottom: 4 }}>
              Paste Their Recent Posts <span style={{ fontWeight: 400, color: "#94a3b8", fontSize: 12 }}>(recommended - filters promotional posts automatically)</span>
            </label>
            <textarea value={posts} onChange={e => setPosts(e.target.value)} placeholder="Paste their LinkedIn posts here. Promotional posts are filtered automatically..." style={{ width: "100%", height: 120, padding: 12, borderRadius: 8, border: "1.5px solid #e2e8f0", fontSize: 13, resize: "vertical", outline: "none", boxSizing: "border-box", color: "#1e293b" }} />
            <button onClick={analyze} disabled={loading || !profile.trim()} style={{ marginTop: 12, width: "100%", padding: "12px 0", background: loading ? "#94a3b8" : "#0f172a", color: "#fff", border: "none", borderRadius: 8, fontSize: 15, fontWeight: 600, cursor: loading ? "not-allowed" : "pointer" }}>
              {loading ? loadingMsg : "Generate Outreach"}
            </button>
            {error && <div style={{ marginTop: 10, color: "#dc2626", fontSize: 13 }}>{error}</div>}
          </div>

          {sections.map(sec => <SectionCard key={sec.id} sec={sec} />)}

          {result && (
            <div style={{ background: "#fff", borderRadius: 12, padding: 20, boxShadow: "0 1px 3px rgba(0,0,0,0.08)", marginTop: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: "#0f172a" }}>Could this be better?</div>
                  <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>Get a coach review of the generated outreach</div>
                </div>
                <button onClick={getCritique} disabled={critiqueLoading} style={{ padding: "8px 18px", borderRadius: 8, border: "1px solid #0ea5e9", background: critiqueLoading ? "#f0f9ff" : "#0ea5e9", color: critiqueLoading ? "#0369a1" : "#fff", fontWeight: 600, fontSize: 13, cursor: critiqueLoading ? "not-allowed" : "pointer" }}>
                  {critiqueLoading ? "Reviewing..." : "Review Outreach"}
                </button>
              </div>
              {critique && (
                <div style={{ background: "#f0f9ff", borderRadius: 8, padding: 16, fontSize: 13, color: "#1e293b", lineHeight: 1.75, whiteSpace: "pre-wrap" }}>
                  {critique}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {view === "history" && !selectedHistory && (
        <div>
          <div style={{ fontSize: 13, color: "#64748b", marginBottom: 12 }}>Click any prospect to view outreach, paste replies, and get next messages.</div>
          {history.length === 0 && <div style={{ textAlign: "center", padding: 60, color: "#94a3b8", fontSize: 14 }}>No profiles generated yet.</div>}
          {history.map(h => (
            <div key={h.id} onClick={() => { setSelectedHistory(h); setReplyResult(""); setReplyInput(""); }} style={{ background: "#fff", borderRadius: 10, padding: "14px 18px", marginBottom: 8, boxShadow: "0 1px 2px rgba(0,0,0,0.06)", cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center", border: "1.5px solid #e2e8f0" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ width: 38, height: 38, borderRadius: "50%", background: "#0f172a", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 15, flexShrink: 0 }}>
                  {h.name.split(" ").map(n => n[0]).slice(0,2).join("")}
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 15, color: "#0f172a" }}>{h.name}</div>
                  <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>{h.date} · {h.decision.substring(0,50)}{h.decision.length > 50 ? "..." : ""}</div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {(h.conversation||[]).length > 0 && <span style={{ fontSize: 11, color: "#0ea5e9", fontWeight: 600 }}>{h.conversation.length} msgs</span>}
                <span style={{ fontSize: 11, fontWeight: 700, color: SC[h.status], background: "#f8fafc", padding: "3px 10px", borderRadius: 20, border: "1px solid " + SC[h.status], whiteSpace: "nowrap" }}>{h.status}</span>
                <span style={{ color: "#cbd5e1" }}>›</span>
                <button onClick={e => { e.stopPropagation(); const updated = history.filter(x => x.id !== h.id); setHistory(updated); try { localStorage.setItem("mb_v7", JSON.stringify(updated)); } catch (err) {} }} style={{ marginLeft: 4, padding: "3px 8px", borderRadius: 6, border: "1px solid #fecaca", background: "#fff1f2", color: "#ef4444", fontWeight: 700, fontSize: 11, cursor: "pointer" }}>✕</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {view === "history" && selectedHistory && (
        <div>
          <button onClick={() => { setSelectedHistory(null); setReplyResult(""); setReplyInput(""); }} style={{ marginBottom: 16, padding: "7px 14px", borderRadius: 8, border: "1px solid #e2e8f0", background: "#fff", color: "#475569", cursor: "pointer", fontWeight: 600, fontSize: 13 }}>Back to History</button>

          <div style={{ background: "#fff", borderRadius: 12, padding: 18, marginBottom: 14, boxShadow: "0 1px 3px rgba(0,0,0,0.08)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 16, color: "#0f172a" }}>{selectedHistory.name}</div>
                <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>{selectedHistory.date}</div>
              </div>
              <select value={selectedHistory.status} onChange={e => updateHistory(selectedHistory.id, { status: e.target.value })} style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                {Object.keys(SC).map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>

          {(selectedHistory.conversation||[]).length > 0 && (
            <div style={{ background: "#fff", borderRadius: 12, padding: 18, marginBottom: 14, boxShadow: "0 1px 3px rgba(0,0,0,0.08)" }}>
              <div style={{ fontWeight: 700, fontSize: 12, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 12 }}>Conversation Log</div>
              {selectedHistory.conversation.map((msg, i) => (
                <div key={i} style={{ display: "flex", justifyContent: msg.from === "Sai" ? "flex-end" : "flex-start", marginBottom: 10 }}>
                  <div style={{ maxWidth: "75%", padding: "10px 14px", borderRadius: 10, background: msg.from === "Sai" ? "#0f172a" : "#f1f5f9", color: msg.from === "Sai" ? "#fff" : "#1e293b", fontSize: 13, lineHeight: 1.6 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, marginBottom: 4, opacity: 0.6 }}>{msg.from}</div>
                    {msg.text}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div style={{ background: "#f0f9ff", border: "1.5px solid #0ea5e9", borderRadius: 12, padding: 18, marginBottom: 14 }}>
            <div style={{ fontWeight: 700, fontSize: 12, color: "#0369a1", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 10 }}>Paste Their Reply</div>
            <textarea value={replyInput} onChange={e => setReplyInput(e.target.value)} placeholder="Paste what they replied and get the next best message..." style={{ width: "100%", height: 100, padding: 12, borderRadius: 8, border: "1.5px solid #bae6fd", fontSize: 13, resize: "vertical", outline: "none", boxSizing: "border-box", color: "#1e293b" }} />
            <button onClick={() => handleReply(selectedHistory)} disabled={replyLoading || !replyInput.trim()} style={{ marginTop: 10, width: "100%", padding: "10px 0", background: replyLoading ? "#94a3b8" : "#0369a1", color: "#fff", border: "none", borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: replyLoading ? "not-allowed" : "pointer" }}>
              {replyLoading ? "Thinking..." : "Generate Next Message"}
            </button>
          </div>

          {replyResult && (() => {
            const p = parseReply(replyResult);
            return (
              <div style={{ background: "#faf5ff", border: "1.5px solid #a855f7", borderRadius: 12, padding: 18, marginBottom: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <span style={{ fontWeight: 700, fontSize: 12, color: "#7e22ce", textTransform: "uppercase", letterSpacing: "0.07em" }}>Next Message</span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: GC[p.stage] || "#94a3b8", background: "#f8fafc", padding: "3px 10px", borderRadius: 20, border: "1px solid " + (GC[p.stage] || "#e2e8f0") }}>{p.stage}</span>
                </div>
                {p.analysis && <div style={{ fontSize: 12, color: "#64748b", marginBottom: 12, fontStyle: "italic" }}>{p.analysis}</div>}
                <div style={{ fontSize: 13, color: "#1e293b", lineHeight: 1.75, whiteSpace: "pre-wrap", marginBottom: 12 }}>{p.message}</div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={() => copyText(p.message, "reply")} style={{ flex: 1, padding: "8px 0", borderRadius: 8, border: "1px solid #a855f7", background: "#fff", color: "#7e22ce", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>{copied === "reply" ? "Copied!" : "Copy Message"}</button>
                  <button onClick={() => saveReplyToConvo(selectedHistory, replyResult)} style={{ flex: 1, padding: "8px 0", borderRadius: 8, border: "none", background: "#0f172a", color: "#fff", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>Save to Log</button>
                </div>
              </div>
            );
          })()}

          {parseResult(selectedHistory.result).map(sec => <SectionCard key={sec.id} sec={sec} />)}
        </div>
      )}
    </div>
  );
}