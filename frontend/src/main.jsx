import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BriefcaseBusiness,
  Camera,
  Check,
  ChevronRight,
  CirclePlus,
  FileText,
  KanbanSquare,
  Lock,
  LoaderCircle,
  LogOut,
  Plus,
  Search,
  Settings,
  Trash2,
  Users,
  X,
} from "lucide-react";
import "./style.css";

const API = "";
async function api(method, path, body) {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || response.statusText);
  }
  return response.json();
}
const esc = (value) => String(value ?? "");
const columns = [
  { key: "new", label: "Saved", color: "#64748b" },
  { key: "applied", label: "Applied", color: "#2563eb" },
  { key: "interviewing", label: "Interviewing", color: "#d97706" },
  { key: "offered", label: "Offers", color: "#059669" },
  { key: "rejected", label: "Rejected", color: "#dc2626" },
];

// ── Profile colour helpers ──────────────────────────────────────────────────
const PROF_COLORS = ["#6366f1","#8b5cf6","#10b981","#f59e0b","#ef4444","#3b82f6","#ec4899","#14b8a6"];
function profColor(id) { return PROF_COLORS[((id || 1) - 1) % PROF_COLORS.length]; }
function profInitials(p) {
  const n = p?.profile_name || p?.full_name || "";
  return n.split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0].toUpperCase()).join("") || "?";
}

function App() {
  const [page, setPage] = useState("feed");
  // ── Login gate ──
  const [loggedIn, setLoggedIn] = useState(() => !!sessionStorage.getItem("jp_session"));
  const [showSwitchModal, setShowSwitchModal] = useState(false);

  const cached = (() => {
    try {
      return JSON.parse(sessionStorage.getItem("jobpilot-cache") || "{}");
    } catch (_) {
      return {};
    }
  })();
  const [jobs, setJobs] = useState(cached.jobs || []);
  const [applications, setApplications] = useState([]);
  const [profiles, setProfiles] = useState(cached.profiles || []);
  const [stats, setStats] = useState(cached.stats || {});
  const [profile, setProfile] = useState(cached.profile || {});
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [dragged, setDragged] = useState(null);
  const [scores, setScores] = useState({});
  const [error, setError] = useState("");
  const [selectedJobs, setSelectedJobs] = useState(new Set());
  const [applying, setApplying] = useState(false);

  const notify = (message) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2600);
  };
  const refresh = async () => {
    try {
      const [j, s, p, allProfiles] = await Promise.all([
        api("GET", "/api/jobs?limit=300"),
        api("GET", "/api/stats"),
        api("GET", "/api/profile"),
        api("GET", "/api/profiles"),
      ]);
      setJobs(j);
      setStats(s);
      setProfile(p || {});
      setProfiles(allProfiles || []);
      sessionStorage.setItem(
        "jobpilot-cache",
        JSON.stringify({
          jobs: j,
          stats: s,
          profile: p || {},
          profiles: allProfiles || [],
        }),
      );
    } catch (e) {
      setError(e.message);
    }
  };
  const enterApp = useCallback(async () => {
    sessionStorage.setItem("jp_session", "1");
    setLoggedIn(true);
    await refresh();
  }, []);

  const openLoginPage = () => {
    sessionStorage.removeItem("jp_session");
    setLoggedIn(false);
  };

  const doSwitchProfile = async (id) => {
    try {
      await api("POST", `/api/profiles/${id}/activate`);
      setScores({});
      setShowSwitchModal(false);
      await refresh();
      notify("Account switched");
    } catch (e) {
      notify(e.message);
    }
  };
  useEffect(() => {
    refresh();
  }, []);
  useEffect(() => {
    if (page === "tracker")
      api("GET", "/api/applications")
        .then(setApplications)
        .catch(() => {});
  }, [page]);

  const search = async () => {
    if (!query.trim()) return notify("Enter a search query");
    setBusy(true);
    try {
      await api("POST", "/api/search", {
        keywords: query,
        location: "",
        sites: ["linkedin", "naukri", "indeed"],
        filters: {},
        results_limit: 25,
      });
      await refresh();
      notify("Search complete");
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };
  const scoreJobs = async () => {
    const ids = jobs.filter((j) => scores[j.id] == null).map((j) => j.id);
    for (let i = 0; i < ids.length; i += 12) {
      try {
        const result = await api("POST", "/api/ai/score-jobs", {
          job_ids: ids.slice(i, i + 12),
        });
        setScores((previous) => ({
          ...previous,
          ...Object.fromEntries(
            (result.results || []).map((item) => [item.id, item.score]),
          ),
        }));
      } catch (_) {
        break;
      }
    }
  };
  useEffect(() => {
    if (jobs.length) scoreJobs();
  }, [jobs.length]);
  const updateStatus = async (id, status) => {
    const before = jobs.find((j) => j.id === id)?.status || "new";
    setJobs((items) => items.map((j) => (j.id === id ? { ...j, status } : j)));
    try {
      await api("PATCH", `/api/jobs/${id}/status`, { status });
      notify("Pipeline stage updated");
    } catch (e) {
      setJobs((items) =>
        items.map((j) => (j.id === id ? { ...j, status: before } : j)),
      );
      notify(e.message);
    }
  };
  const removeJob = async (id) => {
    if (!window.confirm("Delete this job and its related records?")) return;
    try {
      await api("DELETE", `/api/jobs/${id}`);
      setJobs((items) => items.filter((j) => j.id !== id));
      notify("Job deleted");
    } catch (e) {
      notify(e.message);
    }
  };
  const clearJobs = async () => {
    if (!window.confirm("Delete all stored jobs?")) return;
    try {
      await api("DELETE", "/api/jobs/all");
      setJobs([]);
      setSelectedJobs(new Set());
      notify("Jobs cleared");
      await refresh();
    } catch (e) {
      notify(e.message);
    }
  };
  const applyJob = async (id) => {
    try {
      const result = await api("POST", `/api/jobs/${id}/apply`);
      await refresh();
      notify(
        result.status === "applied"
          ? "Application submitted"
          : "Manual application needed",
      );
    } catch (e) {
      notify(e.message);
    }
  };
  const toggleJob = (id) =>
    setSelectedJobs((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const applySelected = async () => {
    if (!selectedJobs.size) return notify("Select jobs first");
    setApplying(true);
    try {
      await api("POST", "/api/jobs/apply-batch", {
        job_ids: [...selectedJobs],
      });
      setSelectedJobs(new Set());
      await refresh();
      notify("Selected applications processed");
    } catch (e) {
      notify(e.message);
    } finally {
      setApplying(false);
    }
  };
  const applyAll = async () => {
    if (
      !window.confirm(
        "Apply to all new jobs? This opens the automated application workflow.",
      )
    )
      return;
    setApplying(true);
    try {
      await api("POST", "/api/apply-all");
      await refresh();
      notify("Bulk application workflow finished");
    } catch (e) {
      notify(e.message);
    } finally {
      setApplying(false);
    }
  };

  // Show login page on fresh session
  if (!loggedIn) {
    return (
      <LoginPage
        profiles={profiles}
        loadProfiles={refresh}
        onEnter={enterApp}
      />
    );
  }

  return (
    <div className="app-shell">
      {showSwitchModal && (
        <ProfileSwitchModal
          profiles={profiles}
          currentId={profile.id}
          onSwitch={doSwitchProfile}
          onClose={() => setShowSwitchModal(false)}
          notify={notify}
        />
      )}
      <aside className="sidebar">
        <div className="brand">
          <strong>JobPilot</strong>
          <small>AI-powered job search</small>
        </div>
        <nav>
          <Nav
            active={page === "feed"}
            icon={<BriefcaseBusiness size={16} />}
            label="Job Feed"
            count={stats.total_jobs}
            onClick={() => setPage("feed")}
          />
          <Nav
            active={page === "tracker"}
            icon={<KanbanSquare size={16} />}
            label="Job Pipeline"
            count={stats.total_applied}
            onClick={() => setPage("tracker")}
          />
          <div className="nav-label">Setup</div>
          <Nav
            active={page === "sites"}
            icon={<Users size={16} />}
            label="Job Sites"
            onClick={() => setPage("sites")}
          />
          <Nav
            active={page === "settings"}
            icon={<Settings size={16} />}
            label="Settings"
            onClick={() => setPage("settings")}
          />
        </nav>
        <div className="connection">
          <span className="dot" /> Backend connected
        </div>
      </aside>
      <main>
        <header>
          <div>
            <small>Workspace</small>
            <h1>
              {page === "feed"
                ? "Job Feed"
                : page === "tracker"
                  ? "Job Pipeline"
                  : page === "sites"
                    ? "Job Sites"
                    : "Settings"}
            </h1>
          </div>
          {/* Profile avatar button — opens switch modal */}
          <button className="profile-btn" onClick={() => setShowSwitchModal(true)}>
            <div className="profile-av" style={{ background: profColor(profile.id) }}>
              {profile.avatar_path
                ? <img src={`/api/profiles/${profile.id}/avatar`} alt="avatar" />
                : profInitials(profile)}
            </div>
            <span>{profile.profile_name || profile.full_name || "Profile"}</span>
            <ChevronRight size={14} />
          </button>
        </header>
        <section className="content">
          {error && <div className="notice error">{error}</div>}
          {page === "feed" && (
            <Feed
              jobs={jobs}
              query={query}
              setQuery={setQuery}
              search={search}
              busy={busy}
              scores={scores}
              removeJob={removeJob}
              applyJob={applyJob}
              selectedJobs={selectedJobs}
              toggleJob={toggleJob}
              applySelected={applySelected}
              applyAll={applyAll}
              applying={applying}
            />
          )}{" "}
          {page === "tracker" && (
            <Pipeline
              jobs={jobs}
              dragged={dragged}
              setDragged={setDragged}
              updateStatus={updateStatus}
              removeJob={removeJob}
            />
          )}{" "}
          {page === "sites" && <Sites notify={notify} />}{" "}
          {page === "settings" && (
            <SettingsView
              profile={profile}
              refresh={refresh}
              notify={notify}
              clearJobs={clearJobs}
              onOpenLogin={openLoginPage}
            />
          )}
        </section>
      </main>
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
function Nav({ active, icon, label, count, onClick }) {
  return (
    <button className={`nav-item ${active ? "active" : ""}`} onClick={onClick}>
      {icon}
      <span>{label}</span>
      {count != null && <b>{count}</b>}
    </button>
  );
}
function Feed({
  jobs,
  query,
  setQuery,
  search,
  busy,
  scores,
  removeJob,
  applyJob,
  selectedJobs,
  toggleJob,
  applySelected,
  applyAll,
  applying,
}) {
  const suggestions = [
    "last 24 hours",
    "in Bengaluru",
    "in Hyderabad",
    "remote",
    "full time",
    "3 years experience",
  ];
  return (
    <>
      {/* ── Careers hero banner ── */}
      <div className="careers-banner">
        <div className="careers-banner-text">
          <h2>Find your next role</h2>
          <p>AI fills every application form — you just click Apply</p>
        </div>
        <button className="primary careers-banner-cta" onClick={() => document.querySelector(".toolbar input")?.focus()}>
          Search Jobs →
        </button>
      </div>
      <div className="hero" style={{display:"none"}}>
        <div>
          <span className="eyebrow">DISCOVER</span>
          <h2>Find your next role</h2>
          <p>Search across your connected job sites.</p>
        </div>
        <Search size={34} />
      </div>
      <div className="toolbar">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
          placeholder="data engineer jobs in Bengaluru"
        />
        <button className="primary" onClick={search} disabled={busy}>
          {busy ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <Search size={16} />
          )}{" "}
          Search
        </button>
      </div>
      <div className="prompt-suggestions">
        <span>Quick add:</span>
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            onClick={() =>
              setQuery((current) =>
                current && !current.toLowerCase().includes(suggestion)
                  ? `${current}, ${suggestion}`
                  : current || suggestion,
              )
            }
          >
            {suggestion}
          </button>
        ))}
      </div>
      {jobs.some((job) => job.status !== "applied") && (
        <div className="bulk-bar">
          <span>{selectedJobs.size} selected</span>
          <button
            className="secondary"
            onClick={applySelected}
            disabled={applying}
          >
            Apply selected
          </button>
          <button className="primary" onClick={applyAll} disabled={applying}>
            {applying ? "Applying…" : "Apply all new"}
          </button>
        </div>
      )}
      <div className="section-heading">
        <div>
          <h2>Latest matches</h2>
          <span>{jobs.length} jobs found</span>
        </div>
      </div>
      <div className="job-list">
        {jobs.length ? (
          jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              score={scores[job.id]}
              removeJob={removeJob}
              applyJob={applyJob}
              selected={selectedJobs.has(job.id)}
              toggleJob={toggleJob}
            />
          ))
        ) : (
          <Empty text="No jobs yet. Run a search to fill your feed." />
        )}
      </div>
    </>
  );
}
function JobCard({ job, score, removeJob, applyJob, selected, toggleJob }) {
  return (
    <article className="job-card">
      <div className="job-main">
        <input
          className="job-check"
          type="checkbox"
          checked={selected}
          onChange={() => toggleJob(job.id)}
          aria-label={`Select ${job.title}`}
        />
        <div className="job-top">
          <span className="site-tag">{esc(job.site)}</span>
          <span className={`status ${job.status || "new"}`}>
            {job.status || "new"}
          </span>
          {score != null && (
            <span
              className={`fit ${score >= 80 ? "high" : score >= 60 ? "mid" : "low"}`}
            >
              {score}% fit
            </span>
          )}
        </div>
        <h3>{esc(job.title)}</h3>
        <p>
          {esc(job.company)} {job.location && `· ${esc(job.location)}`}
        </p>
      </div>
      <div className="job-actions">
        <a href={job.url} target="_blank">
          View
        </a>
        <button
          className="icon-btn danger"
          title="Delete job"
          onClick={() => removeJob(job.id)}
        >
          <Trash2 size={15} />
        </button>
        <button
          className="primary"
          onClick={() => applyJob(job.id)}
          disabled={job.status === "applied"}
        >
          {job.status === "applied" ? "Applied" : "Apply"}
        </button>
      </div>
    </article>
  );
}
function Pipeline({ jobs, dragged, setDragged, updateStatus, removeJob }) {
  const [applications, setApplications] = useState([]);
  const load = () =>
    api("GET", "/api/applications")
      .then(setApplications)
      .catch(() => {});
  useEffect(() => {
    load();
  }, []);
  const update = async (id, status) => {
    try {
      await api("PATCH", `/api/applications/${id}`, { status });
      setApplications((items) =>
        items.map((item) => (item.id === id ? { ...item, status } : item)),
      );
    } catch (e) {
      window.alert(e.message);
    }
  };
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>Job pipeline</h2>
          <span>
            The board tracks jobs from the feed. Application records are
            separate.
          </span>
        </div>
      </div>
      <div className="kanban">
        {columns.map((column) => (
          <div
            className="column"
            key={column.key}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (dragged) updateStatus(dragged, column.key);
              setDragged(null);
            }}
          >
            <div
              className="column-title"
              style={{ borderTopColor: column.color }}
            >
              <strong>{column.label}</strong>
              <b>
                {jobs.filter((j) => (j.status || "new") === column.key).length}
              </b>
            </div>
            <div className="column-body">
              {jobs
                .filter((j) => (j.status || "new") === column.key)
                .map((job) => (
                  <div
                    className="kanban-card"
                    key={job.id}
                    draggable
                    onDragStart={() => setDragged(job.id)}
                    onDragEnd={() => setDragged(null)}
                  >
                    <strong>{esc(job.title)}</strong>
                    <span>{esc(job.company)}</span>
                    <select
                      value={job.status || "new"}
                      onChange={(e) => updateStatus(job.id, e.target.value)}
                    >
                      <option value="new">Saved</option>
                      <option value="applied">Applied</option>
                      <option value="interviewing">Interviewing</option>
                      <option value="offered">Offered</option>
                      <option value="rejected">Rejected</option>
                    </select>
                    <button
                      className="text-danger"
                      onClick={() => removeJob(job.id)}
                    >
                      <Trash2 size={13} /> Delete
                    </button>
                  </div>
                ))}
            </div>
          </div>
        ))}
      </div>
      <div className="section-heading">
        <div>
          <h2>Submitted applications</h2>
          <span>Statuses for roles where an application record exists.</span>
        </div>
      </div>
      <div className="job-list">
        {applications.length ? (
          applications.map((item) => (
            <article className="job-card" key={item.id}>
              <div>
                <h3>{esc(item.title)}</h3>
                <p>
                  {esc(item.company)} · {esc(item.site)}
                </p>
              </div>
              <select
                className="app-status"
                value={item.status}
                onChange={(e) => update(item.id, e.target.value)}
              >
                <option value="applied">Applied</option>
                <option value="interviewing">Interviewing</option>
                <option value="offered">Offered</option>
                <option value="rejected">Rejected</option>
                <option value="withdrawn">Withdrawn</option>
              </select>
            </article>
          ))
        ) : (
          <Empty text="No submitted applications yet." />
        )}
      </div>
    </>
  );
}
function Sites({ notify }) {
  const [sites, setSites] = useState([]);
  const load = () =>
    api("GET", "/api/credentials")
      .then(setSites)
      .catch(() => {});
  useEffect(() => {
    load();
  }, []);
  const connected = (site) => sites.some((item) => item.site === site);
  const toggle = async (site) => {
    try {
      if (connected(site)) {
        await api("DELETE", `/api/credentials/${site}`);
        notify(`${site} disconnected`);
      } else {
        await api("POST", `/api/login/${site}/sso`);
        notify(`${site} connected`);
      }
      load();
    } catch (e) {
      notify(e.message);
    }
  };
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>Job Sites</h2>
          <span>Connect once and reuse your saved browser session.</span>
        </div>
      </div>
      <div className="site-grid">
        {["linkedin", "naukri", "indeed", "glassdoor", "instahyre"].map(
          (site) => (
            <div className="site-card" key={site}>
              <div className="site-avatar">
                {site.slice(0, 2).toUpperCase()}
              </div>
              <div>
                <h3>{site}</h3>
                <span className={connected(site) ? "connected" : ""}>
                  {connected(site) ? "Connected" : "Not connected"}
                </span>
              </div>
              <button className="secondary" onClick={() => toggle(site)}>
                {connected(site) ? "Disconnect" : "Connect"}
              </button>
            </div>
          ),
        )}
      </div>
    </>
  );
}
function SettingsView({ profile, refresh, notify, clearJobs, onOpenLogin }) {
  const [name, setName] = useState(profile.profile_name || "");
  const [fullName, setFullName] = useState(profile.full_name || "");
  const [email, setEmail] = useState(profile.email || "");
  const [phone, setPhone] = useState(profile.phone || "");
  const [location, setLocation] = useState(profile.location || "");
  const [title, setTitle] = useState(profile.current_title || "");
  const [desired, setDesired] = useState(profile.desired_title || "");
  const [salary, setSalary] = useState(profile.desired_salary || "");
  const [experience, setExperience] = useState(profile.years_experience || 0);
  const [summary, setSummary] = useState(profile.summary || "");
  const [skills, setSkills] = useState(profile.skills || []);
  const [key, setKey] = useState("");
  const [resumeBusy, setResumeBusy] = useState(false);
  const [searches, setSearches] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [searchName, setSearchName] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const load = () =>
    Promise.all([
      api("GET", "/api/saved-searches"),
      api("GET", "/api/reminders?status=pending"),
    ])
      .then(([s, r]) => {
        setSearches(s);
        setReminders(r);
      })
      .catch(() => {});
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    setName(profile.profile_name || "");
    setFullName(profile.full_name || "");
    setEmail(profile.email || "");
    setPhone(profile.phone || "");
    setLocation(profile.location || "");
    setTitle(profile.current_title || "");
    setDesired(profile.desired_title || "");
    setSalary(profile.desired_salary || "");
    setExperience(profile.years_experience || 0);
    setSummary(profile.summary || "");
    setSkills(profile.skills || []);
  }, [profile.id]);
  const saveProfile = async (data = {}) => {
    await api("POST", "/api/profile", {
      profile_name: name,
      full_name: fullName,
      email,
      phone,
      location,
      current_title: title,
      desired_title: desired,
      desired_salary: salary,
      years_experience: Number(experience) || 0,
      summary,
      skills,
      ...data,
    });
    await refresh();
  };
  const uploadResume = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setResumeBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const upload = await fetch("/api/upload-resume", {
        method: "POST",
        body: form,
      });
      if (!upload.ok) throw new Error("Resume upload failed");
      const result = await upload.json();
      await saveProfile({ resume_path: result.path });
      const parsed = await api("POST", "/api/ai/parse-resume");
      const extracted = parsed.extracted || {};
      setFullName(extracted.full_name || fullName);
      setEmail(extracted.email || email);
      setPhone(extracted.phone || phone);
      setLocation(extracted.location || location);
      setTitle(extracted.current_title || title);
      setExperience(extracted.years_experience || experience);
      setSummary(extracted.summary || summary);
      setSkills([...new Set([...(skills || []), ...(extracted.skills || [])])]);
      await saveProfile({
        ...extracted,
        resume_path: result.path,
        skills: [...new Set([...(skills || []), ...(extracted.skills || [])])],
      });
      notify("Resume uploaded and profile parsed");
    } catch (e) {
      notify(e.message);
    } finally {
      setResumeBusy(false);
    }
  };
  const saveSearch = async () => {
    if (!searchQuery.trim()) return notify("Enter search keywords");
    try {
      await api("POST", "/api/saved-searches", {
        name: searchName || "Saved Search",
        keywords: searchQuery,
        location: "",
        sites: [],
        filters: {},
      });
      setSearchName("");
      setSearchQuery("");
      load();
      notify("Saved search created");
    } catch (e) {
      notify(e.message);
    }
  };
  const done = async (id) => {
    try {
      await api("PATCH", `/api/reminders/${id}/done`);
      load();
      notify("Reminder completed");
    } catch (e) {
      notify(e.message);
    }
  };
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>Settings</h2>
          <span>Profile, saved searches, reminders, and local data.</span>
        </div>
      </div>
      <div className="settings-card">
        <label>
          Profile name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <div className="settings-grid-two">
          <label>
            Full name
            <input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </label>
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            Phone
            <input value={phone} onChange={(e) => setPhone(e.target.value)} />
          </label>
          <label>
            Location
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
          </label>
        </div>
        <label>
          Current title
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          Desired title
          <input value={desired} onChange={(e) => setDesired(e.target.value)} />
        </label>
        <div className="settings-grid-two">
          <label>
            Expected salary
            <input value={salary} onChange={(e) => setSalary(e.target.value)} />
          </label>
          <label>
            Years of experience
            <input
              type="number"
              value={experience}
              onChange={(e) => setExperience(e.target.value)}
            />
          </label>
        </div>
        <label>
          Professional summary
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
          />
        </label>
        <label>
          Skills
          <input
            value={skills.join(", ")}
            onChange={(e) =>
              setSkills(
                e.target.value
                  .split(",")
                  .map((item) => item.trim())
                  .filter(Boolean),
              )
            }
            placeholder="python, fastapi, sql"
          />
        </label>
        <button
          className="primary"
          onClick={async () => {
            try {
              await api("POST", "/api/profile", {
                profile_name: name,
                full_name: fullName,
                email,
                phone,
                location,
                current_title: title,
                desired_title: desired,
                desired_salary: salary,
                years_experience: Number(experience) || 0,
                summary,
                skills,
              });
              await refresh();
              notify("Profile saved");
            } catch (e) {
              notify(e.message);
            }
          }}
        >
          <Check size={16} /> Save profile
        </button>
        <hr />
        <label>
          Anthropic API key
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="sk-ant-api..."
          />
        </label>
        <button
          className="secondary"
          onClick={async () => {
            try {
              await api("POST", "/api/ai/key", { key });
              setKey("");
              notify("AI key saved");
            } catch (e) {
              notify(e.message);
            }
          }}
        >
          Save AI key
        </button>
      </div>
      <div className="settings-card">
        <h3>Resume</h3>
        <p>
          {profile.resume_path
            ? `Uploaded: ${profile.resume_path.split("/").pop()}`
            : "Upload a PDF or DOCX and JobPilot will parse it into your profile."}
        </p>
        <label className="upload-button">
          {resumeBusy ? "Parsing resume…" : "Upload and parse resume"}
          <input
            type="file"
            accept=".pdf,.doc,.docx"
            onChange={uploadResume}
            disabled={resumeBusy}
          />
        </label>
      </div>
      <div className="settings-card">
        <h3>Saved searches</h3>
        <div className="inline-form">
          <input
            value={searchName}
            onChange={(e) => setSearchName(e.target.value)}
            placeholder="Name"
          />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Keywords"
          />
          <button className="primary" onClick={saveSearch}>
            <CirclePlus size={15} /> Save
          </button>
        </div>
        {searches.map((item) => (
          <div className="setting-row" key={item.id}>
            <span>
              <strong>{esc(item.name)}</strong>
              <small>{esc(item.keywords)}</small>
            </span>
            <button
              className="text-danger"
              onClick={async () => {
                await api("DELETE", `/api/saved-searches/${item.id}`);
                load();
              }}
            >
              <Trash2 size={14} /> Delete
            </button>
          </div>
        ))}
      </div>
      <div className="settings-card">
        <h3>Upcoming reminders</h3>
        {reminders.length ? (
          reminders.map((item) => (
            <div className="setting-row" key={item.id}>
              <span>
                <strong>{esc(item.reminder_type || "follow up")}</strong>
                <small>
                  {esc(item.note || "")} · {esc(item.due_at)}
                </small>
              </span>
              <button className="secondary" onClick={() => done(item.id)}>
                Done
              </button>
            </div>
          ))
        ) : (
          <small>No upcoming reminders.</small>
        )}
      </div>
      <div className="settings-card danger-panel">
        <h3>Data</h3>
        <p>Remove all stored jobs and related application records.</p>
        <button className="secondary danger-button" onClick={clearJobs}>
          <Trash2 size={15} /> Clear all jobs
        </button>
        <hr />
        <p>Switch to a different account or create a new one.</p>
        <button className="secondary" onClick={onOpenLogin}>
          <LogOut size={15} /> Switch account
        </button>
      </div>
    </>
  );
}
function Empty({ text }) {
  return (
    <div className="empty">
      <FileText size={30} />
      <p>{text}</p>
    </div>
  );
}

// ── LoginPage ───────────────────────────────────────────────────────────────
function LoginPage({ profiles: initialProfiles, loadProfiles, onEnter }) {
  const [profiles, setProfiles] = useState(initialProfiles || []);
  const [view, setView] = useState("picker"); // "picker" | "password" | "new"
  const [target, setTarget] = useState(null);
  const [pw, setPw] = useState("");
  const [pwErr, setPwErr] = useState("");
  const [newName, setNewName] = useState("");
  const [newErr, setNewErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("GET", "/api/profiles")
      .then(setProfiles)
      .catch(() => {});
  }, []);

  const handleCardClick = (p) => {
    if (p.is_active && !p.has_password) { onEnter(); return; }
    if (p.has_password) { setTarget(p); setPw(""); setPwErr(""); setView("password"); }
    else activateAndEnter(p.id);
  };

  const activateAndEnter = async (id) => {
    setBusy(true);
    try {
      await api("POST", `/api/profiles/${id}/activate`);
      onEnter();
    } catch (e) { setPwErr(e.message); }
    finally { setBusy(false); }
  };

  const submitPassword = async () => {
    if (!pw) { setPwErr("Enter your password"); return; }
    setBusy(true);
    try {
      await api("POST", `/api/profiles/${target.id}/verify-password`, { password: pw });
      await activateAndEnter(target.id);
    } catch (_) {
      setPwErr("Incorrect password");
      setPw("");
    } finally { setBusy(false); }
  };

  const createProfile = async () => {
    if (!newName.trim()) { setNewErr("Enter a name"); return; }
    setBusy(true);
    try {
      const created = await api("POST", "/api/profiles", { name: newName.trim() });
      await api("POST", `/api/profiles/${created.id}/activate`);
      onEnter();
    } catch (e) { setNewErr(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="login-page">
      {/* Left panel — office hero image */}
      <div className="login-left">
        <div className="login-left-overlay">
          <div className="login-left-quote">
            <div>Better Jobs.<br />Brighter Futures.</div>
            <p>AI-powered job search that works while you sleep.</p>
          </div>
        </div>
      </div>

      {/* Right panel — profile picker */}
      <div className="login-right">
        <div className="login-brand">
          <strong>JobPilot</strong>
          <span>Choose your account to continue</span>
        </div>

        {view === "picker" && (
          <>
            <div className="login-grid">
              {profiles.map((p) => (
                <button
                  key={p.id}
                  className={`login-card ${p.is_active ? "active" : ""}`}
                  onClick={() => handleCardClick(p)}
                >
                  <div className="login-av" style={{ background: profColor(p.id) }}>
                    {p.avatar_path
                      ? <img src={`/api/profiles/${p.id}/avatar`} alt="avatar" />
                      : profInitials(p)}
                  </div>
                  {p.has_password && <span className="login-lock"><Lock size={9} /></span>}
                  <span className="login-card-name">{p.profile_name || "Unnamed"}</span>
                  <span className="login-card-title">{p.current_title || ""}</span>
                  {p.is_active && <span className="login-badge">Active</span>}
                </button>
              ))}
              <button className="login-card login-add" onClick={() => { setNewName(""); setNewErr(""); setView("new"); }}>
                <div className="login-av login-av-add"><Plus size={24} /></div>
                <span className="login-card-name">New Profile</span>
              </button>
            </div>
            <button className="login-skip" onClick={onEnter}>Skip →</button>
          </>
        )}

        {view === "password" && (
          <div className="login-pw-screen">
            <div className="login-av lg" style={{ background: profColor(target?.id) }}>
              {target?.avatar_path
                ? <img src={`/api/profiles/${target.id}/avatar`} alt="avatar" />
                : profInitials(target)}
            </div>
            <strong>{target?.profile_name || "Profile"}</strong>
            <input
              type="password"
              value={pw}
              onChange={(e) => { setPw(e.target.value); setPwErr(""); }}
              onKeyDown={(e) => e.key === "Enter" && submitPassword()}
              placeholder="Password"
              autoFocus
              className="login-pw-input"
            />
            {pwErr && <span className="login-err">{pwErr}</span>}
            <button className="login-btn-primary" onClick={submitPassword} disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={16} /> : <><Lock size={14} /> Unlock</>}
            </button>
            <button className="login-back" onClick={() => setView("picker")}>← Back</button>
          </div>
        )}

        {view === "new" && (
          <div className="login-pw-screen">
            <strong style={{fontSize:"16px",marginBottom:"4px"}}>New Account</strong>
            <input
              type="text"
              value={newName}
              onChange={(e) => { setNewName(e.target.value); setNewErr(""); }}
              onKeyDown={(e) => e.key === "Enter" && createProfile()}
              placeholder='e.g. "Senior Backend Engineer"'
              autoFocus
              className="login-pw-input"
            />
            {newErr && <span className="login-err">{newErr}</span>}
            <button className="login-btn-primary" onClick={createProfile} disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={16} /> : "Create & Enter"}
            </button>
            <button className="login-back" onClick={() => setView("picker")}>← Cancel</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── ProfileSwitchModal ───────────────────────────────────────────────────────
function ProfileSwitchModal({ profiles, currentId, onSwitch, onClose, notify }) {
  const [view, setView] = useState("list"); // "list" | "password"
  const [target, setTarget] = useState(null);
  const [pw, setPw] = useState("");
  const [pwErr, setPwErr] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSelect = (p) => {
    if (String(p.id) === String(currentId)) { onClose(); return; }
    if (p.has_password) { setTarget(p); setPw(""); setPwErr(""); setView("password"); }
    else onSwitch(p.id);
  };

  const submitPw = async () => {
    if (!pw) { setPwErr("Enter password"); return; }
    setBusy(true);
    try {
      await api("POST", `/api/profiles/${target.id}/verify-password`, { password: pw });
      onSwitch(target.id);
    } catch (_) { setPwErr("Incorrect password"); setPw(""); }
    finally { setBusy(false); }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="switch-modal" onClick={(e) => e.stopPropagation()}>
        <div className="switch-modal-header">
          <span>Switch Account</span>
          <button onClick={onClose}><X size={16} /></button>
        </div>

        {view === "list" && (
          <div className="switch-modal-list">
            {profiles.map((p) => (
              <button
                key={p.id}
                className={`switch-item ${String(p.id) === String(currentId) ? "active" : ""}`}
                onClick={() => handleSelect(p)}
              >
                <div className="switch-av" style={{ background: profColor(p.id) }}>
                  {p.avatar_path
                    ? <img src={`/api/profiles/${p.id}/avatar`} alt="avatar" />
                    : profInitials(p)}
                </div>
                <div className="switch-info">
                  <strong>{p.profile_name || "Unnamed"}</strong>
                  <span>{p.current_title || ""}</span>
                </div>
                {p.has_password && <Lock size={13} style={{color:"#94a3b8",flexShrink:0}} />}
                {String(p.id) === String(currentId) && <span className="switch-badge">Active</span>}
              </button>
            ))}
          </div>
        )}

        {view === "password" && (
          <div className="switch-modal-pw">
            <div className="switch-av lg" style={{ background: profColor(target?.id) }}>
              {target?.avatar_path
                ? <img src={`/api/profiles/${target.id}/avatar`} alt="avatar" />
                : profInitials(target)}
            </div>
            <strong>{target?.profile_name}</strong>
            <input
              type="password"
              value={pw}
              onChange={(e) => { setPw(e.target.value); setPwErr(""); }}
              onKeyDown={(e) => e.key === "Enter" && submitPw()}
              placeholder="Password"
              autoFocus
              className="switch-pw-input"
            />
            {pwErr && <span className="switch-err">{pwErr}</span>}
            <button className="primary" onClick={submitPw} disabled={busy} style={{width:"100%"}}>
              {busy ? <LoaderCircle className="spin" size={15} /> : "Unlock"}
            </button>
            <button className="login-back" onClick={() => setView("list")}>← Back</button>
          </div>
        )}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
