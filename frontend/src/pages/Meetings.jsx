import { useEffect, useState, useRef } from "react";
import {
  getMeetings, createMeeting, deleteMeeting, updateMeeting,
  updateActionItem, getProjects,
  summarizeMeeting, transcribeMeeting, fullPipeline,
} from "../api/client";
import { Plus, Trash2, Check, Users, Sparkles, Mic, Upload, FileText, RefreshCw } from "lucide-react";
import Modal from "../components/Modal";

// ── Meeting form ──────────────────────────────────────────────────────────────
function MeetingForm({ projects, onSave, onClose }) {
  const [form, setForm] = useState({
    title: "", held_at: new Date().toISOString().slice(0, 16),
    attendees: "", agenda: "", project_id: "",
  });
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.title.trim()) return;
    await createMeeting({
      ...form,
      held_at: new Date(form.held_at).toISOString(),
      project_id: form.project_id || null,
      action_items: [],
    });
    onSave();
  };

  return (
    <>
      <div className="form-group">
        <label className="form-label">Meeting Title *</label>
        <input className="form-input" value={form.title} onChange={e => set("title", e.target.value)}
          placeholder="e.g. Powertrain Review" autoFocus />
      </div>
      <div className="form-row">
        <div className="form-group">
          <label className="form-label">Date & Time</label>
          <input type="datetime-local" className="form-input" value={form.held_at} onChange={e => set("held_at", e.target.value)} />
        </div>
        <div className="form-group">
          <label className="form-label">Project</label>
          <select className="form-select" value={form.project_id} onChange={e => set("project_id", e.target.value)}>
            <option value="">— None —</option>
            {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
      </div>
      <div className="form-group">
        <label className="form-label">Attendees (comma separated)</label>
        <input className="form-input" value={form.attendees} onChange={e => set("attendees", e.target.value)}
          placeholder="Atharv, Akash, Rohan" />
      </div>
      <div className="form-group">
        <label className="form-label">Agenda</label>
        <textarea className="form-textarea" value={form.agenda} onChange={e => set("agenda", e.target.value)}
          style={{ minHeight: 70 }} placeholder="What will be discussed?" />
      </div>
      <div className="modal-footer">
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={submit}>Save Meeting</button>
      </div>
    </>
  );
}

// ── Intelligence panel (transcript + AI) ─────────────────────────────────────
function IntelligencePanel({ meeting, onUpdated }) {
  const [transcript, setTranscript] = useState(meeting.raw_transcript || "");
  const [processing, setProcessing] = useState("");   // "summarizing" | "transcribing" | "pipeline"
  const [saveTimer, setSaveTimer]   = useState(null);
  const audioRef = useRef();

  // Auto-save transcript edits
  const handleTranscriptChange = (val) => {
    setTranscript(val);
    if (saveTimer) clearTimeout(saveTimer);
    setSaveTimer(setTimeout(async () => {
      await updateMeeting(meeting.id, { raw_transcript: val });
    }, 900));
  };

  const handleSummarize = async () => {
    // Save latest transcript first
    await updateMeeting(meeting.id, { raw_transcript: transcript });
    setProcessing("summarizing");
    try {
      await summarizeMeeting(meeting.id);
      onUpdated();
    } catch (e) {
      alert("Summarization failed: " + (e.response?.data?.detail || e.message));
    } finally { setProcessing(""); }
  };

  const handleAudioUpload = async (e, mode) => {
    const file = e.target.files[0]; if (!file) return;
    setProcessing(mode);
    try {
      if (mode === "transcribe") {
        const r = await transcribeMeeting(meeting.id, file);
        setTranscript(r.transcript);
        onUpdated();
      } else {
        await fullPipeline(meeting.id, file);
        onUpdated();
      }
    } catch (err) {
      alert("Failed: " + (err.response?.data?.detail || err.message));
    } finally { setProcessing(""); e.target.value = ""; }
  };

  const busy = !!processing;

  return (
    <div style={{ marginTop: 20 }}>
      <div style={{
        background: "rgba(79,124,255,.06)", border: "1px solid rgba(79,124,255,.2)",
        borderRadius: 12, padding: 16,
      }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
          <Sparkles size={14} color="var(--accent)" />
          <span style={{ fontWeight: 600, fontSize: 13, color: "var(--accent)" }}>Meeting Intelligence</span>
        </div>

        {/* Transcript input */}
        <div className="form-group">
          <label className="form-label" style={{ display: "flex", justifyContent: "space-between" }}>
            <span>Raw Transcript</span>
            <span style={{ fontSize: 10, color: "var(--muted)", fontWeight: 400 }}>auto-saved</span>
          </label>
          <textarea
            className="form-textarea"
            value={transcript}
            onChange={e => handleTranscriptChange(e.target.value)}
            placeholder="Paste your meeting transcript here, or upload an audio file below…"
            style={{ minHeight: 120, fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}
          />
        </div>

        {/* Action buttons */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {/* Summarize text transcript */}
          <button
            className="btn btn-primary btn-sm"
            onClick={handleSummarize}
            disabled={busy || !transcript.trim()}
          >
            {processing === "summarizing"
              ? <><RefreshCw size={12} style={{ animation: "spin .6s linear infinite" }} /> Summarizing…</>
              : <><Sparkles size={12} /> Summarize with AI</>}
          </button>

          {/* Upload audio → transcribe only */}
          <input ref={audioRef} type="file" style={{ display: "none" }}
            accept=".mp3,.mp4,.m4a,.wav,.webm,.ogg,.flac"
            onChange={e => handleAudioUpload(e, "transcribe")} />
          <button className="btn btn-ghost btn-sm" disabled={busy}
            onClick={() => { audioRef.current.dataset.mode = "transcribe"; audioRef.current.click(); }}>
            {processing === "transcribe"
              ? <><RefreshCw size={12} style={{ animation: "spin .6s linear infinite" }} /> Transcribing…</>
              : <><Mic size={12} /> Upload Audio (Whisper)</>}
          </button>

          {/* Upload audio → full pipeline */}
          <input type="file" style={{ display: "none" }} id={`pipeline-${meeting.id}`}
            accept=".mp3,.mp4,.m4a,.wav,.webm,.ogg,.flac"
            onChange={e => handleAudioUpload(e, "pipeline")} />
          <button className="btn btn-ghost btn-sm" disabled={busy}
            onClick={() => document.getElementById(`pipeline-${meeting.id}`).click()}>
            {processing === "pipeline"
              ? <><RefreshCw size={12} style={{ animation: "spin .6s linear infinite" }} /> Processing…</>
              : <><Upload size={12} /> Audio → Full Pipeline</>}
          </button>
        </div>

        {busy && (
          <p style={{ fontSize: 11, color: "var(--muted)", marginTop: 10 }}>
            {processing === "summarizing" && "GPT-4o is reading your transcript…"}
            {processing === "transcribe"  && "Whisper is transcribing your audio (30s–2min)…"}
            {processing === "pipeline"    && "Transcribing then summarizing — hang tight (1–3 min)…"}
          </p>
        )}

        <div style={{ marginTop: 10, fontSize: 11, color: "var(--muted)" }}>
          Supported audio: mp3, mp4, m4a, wav, webm, ogg, flac (max 25 MB)
        </div>
      </div>
    </div>
  );
}

// ── Main meetings page ────────────────────────────────────────────────────────
export default function Meetings() {
  const [meetings, setMeetings]   = useState([]);
  const [projects, setProjects]   = useState([]);
  const [selected, setSelected]   = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [showIntel, setShowIntel] = useState(false);

  const load = async () => {
    try {
      const [m, p] = await Promise.all([getMeetings(), getProjects()]);
      setMeetings(m); setProjects(p);
    } catch {}
  };

  const reloadSelected = async () => {
    await load();
    if (selected) {
      // Refresh selected meeting from updated list
      const fresh = await getMeetings();
      const updated = fresh.find(m => m.id === selected.id);
      if (updated) setSelected(updated);
    }
  };

  useEffect(() => { load(); }, []);

  const toggleAction = async (item) => {
    await updateActionItem(selected.id, item.id, { is_done: !item.is_done });
    reloadSelected();
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this meeting and all its action items?")) return;
    await deleteMeeting(id); setSelected(null); load();
  };

  const projectName = (id) => projects.find(p => p.id === id)?.name;

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      {/* ── List sidebar ── */}
      <div style={{ width: 280, borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column" }}>
        <div style={{
          padding: "16px 12px 8px", display: "flex", justifyContent: "space-between",
          alignItems: "center", borderBottom: "1px solid var(--border)",
        }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Meetings</span>
          <button className="btn btn-ghost btn-sm" onClick={() => setShowModal(true)}><Plus size={14} /></button>
        </div>
        <div style={{ overflowY: "auto", flex: 1 }}>
          {meetings.map(m => (
            <div key={m.id} onClick={() => { setSelected(m); setShowIntel(false); }}
              style={{
                margin: 8, borderRadius: 8, padding: "10px 12px", cursor: "pointer",
                background: selected?.id === m.id ? "var(--surface2)" : "transparent",
                border: "1px solid transparent",
                borderLeft: selected?.id === m.id ? "3px solid var(--accent)" : "3px solid transparent",
              }}>
              <div style={{ fontWeight: 500, fontSize: 13 }}>{m.title}</div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 3, display: "flex", gap: 6, alignItems: "center" }}>
                <span>{new Date(m.held_at).toLocaleDateString()}</span>
                {m.summary && <span style={{ color: "var(--success)" }}>✓ summarized</span>}
                {!m.summary && m.raw_transcript && <span style={{ color: "var(--warning)" }}>transcript ready</span>}
              </div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                {m.action_items?.length || 0} action items
              </div>
            </div>
          ))}
          {meetings.length === 0 && (
            <div className="empty" style={{ padding: 24 }}>
              <Users size={24} style={{ margin: "0 auto 8px", display: "block", opacity: .3 }} />
              <p style={{ fontSize: 12 }}>No meetings yet</p>
            </div>
          )}
        </div>
      </div>

      {/* ── Detail panel ── */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {selected ? (
          <div style={{ padding: 24 }}>
            {/* Meeting header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
              <div>
                <h2 style={{ fontSize: 18, fontWeight: 700 }}>{selected.title}</h2>
                <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
                  {new Date(selected.held_at).toLocaleString()}
                  {selected.project_id && ` · 📁 ${projectName(selected.project_id)}`}
                </p>
                {selected.attendees && (
                  <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>👥 {selected.attendees}</p>
                )}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button
                  className={`btn btn-sm ${showIntel ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setShowIntel(v => !v)}
                  title="Meeting Intelligence"
                >
                  <Sparkles size={12} /> AI
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(selected.id)}>
                  <Trash2 size={12} />
                </button>
              </div>
            </div>

            {/* Agenda */}
            {selected.agenda && (
              <div className="card" style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 8 }}>Agenda</div>
                <p style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{selected.agenda}</p>
              </div>
            )}

            {/* AI Summary */}
            {selected.summary && (
              <div className="card" style={{ marginBottom: 14, borderColor: "rgba(79,124,255,.3)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
                  <Sparkles size={12} color="var(--accent)" />
                  <span style={{ fontSize: 11, fontWeight: 600, color: "var(--accent)", textTransform: "uppercase", letterSpacing: ".05em" }}>AI Summary</span>
                </div>
                <p style={{ fontSize: 13, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{selected.summary}</p>
              </div>
            )}

            {/* Action items */}
            {selected.action_items?.length > 0 && (
              <div className="card" style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 12 }}>
                  Action Items ({selected.action_items.filter(a => !a.is_done).length} open)
                </div>
                <div className="task-list">
                  {selected.action_items.map(item => (
                    <div key={item.id} className="task-item">
                      <button className={`task-check ${item.is_done ? "done" : ""}`} onClick={() => toggleAction(item)}>
                        {item.is_done && <Check size={10} />}
                      </button>
                      <div className="task-body">
                        <div className={`task-title ${item.is_done ? "done" : ""}`}>{item.description}</div>
                        <div className="task-meta">
                          {item.assignee && <span>👤 {item.assignee}</span>}
                          {item.due_date && <span>📅 {new Date(item.due_date).toLocaleDateString()}</span>}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* No summary yet prompt */}
            {!selected.summary && !showIntel && (
              <div style={{
                background: "rgba(79,124,255,.06)", border: "1px dashed rgba(79,124,255,.3)",
                borderRadius: 10, padding: 16, textAlign: "center",
              }}>
                <Sparkles size={20} color="var(--accent)" style={{ margin: "0 auto 8px", display: "block" }} />
                <p style={{ fontSize: 13, color: "var(--muted)" }}>No AI summary yet.</p>
                <button className="btn btn-primary btn-sm" style={{ marginTop: 10 }} onClick={() => setShowIntel(true)}>
                  Open Meeting Intelligence
                </button>
              </div>
            )}

            {/* Intelligence panel */}
            {showIntel && (
              <IntelligencePanel
                meeting={selected}
                onUpdated={() => reloadSelected()}
              />
            )}
          </div>
        ) : (
          <div className="empty" style={{ marginTop: 80 }}>
            <Users size={40} style={{ margin: "0 auto 12px", display: "block", opacity: .3 }} />
            <p>Select a meeting to view details</p>
            <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => setShowModal(true)}>
              <Plus size={14} /> New Meeting
            </button>
          </div>
        )}
      </div>

      {showModal && (
        <Modal title="Log Meeting" onClose={() => setShowModal(false)}>
          <MeetingForm
            projects={projects}
            onSave={() => { setShowModal(false); load(); }}
            onClose={() => setShowModal(false)}
          />
        </Modal>
      )}
    </div>
  );
}
