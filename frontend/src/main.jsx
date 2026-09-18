import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BriefcaseBusiness,
  Check,
  ChevronRight,
  CirclePlus,
  FileText,
  KanbanSquare,
  LoaderCircle,
  LogOut,
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

function App() {
  const [page, setPage] = useState("feed");
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
  const switchProfile = async (id) => {
    try {
      await api("POST", `/api/profiles/${id}/activate`);
      await refresh();
      notify("Profile switched");
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

  return (
    <div className="app-shell">
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
          <select
            className="profile"
            value={profile.id || ""}
            onChange={(e) => switchProfile(e.target.value)}
          >
            <option value="">
              {profile.profile_name || profile.full_name || "Profile"}
            </option>
            {profiles
              .filter((item) => item.id !== profile.id)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.profile_name || item.full_name || `Profile ${item.id}`}
                </option>
              ))}
          </select>
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
            <SettingsView profile={profile} refresh={refresh} notify={notify} />
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
}) {
  return (
    <>
      <div className="hero">
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
            />
          ))
        ) : (
          <Empty text="No jobs yet. Run a search to fill your feed." />
        )}
      </div>
    </>
  );
}
function JobCard({ job, score, removeJob, applyJob }) {
  return (
    <article className="job-card">
      <div className="job-main">
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
function SettingsView({ profile, refresh, notify }) {
  const [name, setName] = useState(profile.profile_name || "");
  const [title, setTitle] = useState(profile.current_title || "");
  const [desired, setDesired] = useState(profile.desired_title || "");
  const [key, setKey] = useState("");
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
  const clearJobs = async () => {
    if (!window.confirm("Delete all stored jobs?")) return;
    try {
      await api("DELETE", "/api/jobs/all");
      notify("Jobs cleared");
      refresh();
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
        <label>
          Current title
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          Desired title
          <input value={desired} onChange={(e) => setDesired(e.target.value)} />
        </label>
        <button
          className="primary"
          onClick={async () => {
            try {
              await api("POST", "/api/profile", {
                profile_name: name,
                current_title: title,
                desired_title: desired,
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

createRoot(document.getElementById("root")).render(<App />);
