import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getIntegrationStatus, getGoogleEvents, getTasks, getProjects, getPlanningDay } from "../api";
import CalendarToolbar from "../components/calendar/CalendarToolbar";
import CalendarConnectionState from "../components/calendar/CalendarConnectionState";
import CalendarGrid from "../components/calendar/CalendarGrid";
import CalendarDayView from "../components/calendar/CalendarDayView";
import CalendarMonthView from "../components/calendar/CalendarMonthView";
import CalendarEventDrawer from "../components/calendar/CalendarEventDrawer";
import DayPlanPanel from "../components/calendar/DayPlanPanel";
import OrbitSkeleton from "../components/ui/OrbitSkeleton";
import {
  weekRange, addDays, buildCalendarEvents, planSignature,
} from "../utils/calendar";

const CHAT_STORAGE_KEY = "ecc_chat_messages";

export default function Calendar() {
  const navigate = useNavigate();

  const [view, setView] = useState("week");
  const [anchor, setAnchor] = useState(() => new Date());

  const [status, setStatus] = useState(null);
  const [events, setEvents] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [eventsError, setEventsError] = useState(false);

  const [drawer, setDrawer] = useState(null);
  const [selectedEvent, setSelectedEvent] = useState(null);

  const [plan, setPlan] = useState(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState(false);
  const [stale, setStale] = useState(false);
  const [checkingSchedule, setCheckingSchedule] = useState(false);
  const [pendingFreshPlan, setPendingFreshPlan] = useState(null);

  const eventTriggerRef = useRef(null);
  const planBtnRef = useRef(null);

  const loadAll = async (quiet = false) => {
    if (!quiet) setLoading(true);
    setLoadError(false);
    setEventsError(false);

    const [sRes, evRes] = await Promise.allSettled([
      getIntegrationStatus(),
      getGoogleEvents(32, 200),
    ]);
    if (sRes.status === "fulfilled") setStatus(sRes.value);
    else setLoadError(true);

    let googleEvents = [];
    if (evRes.status === "fulfilled") googleEvents = evRes.value.events || [];
    else setEventsError(true);

    const [tRes, pRes] = await Promise.allSettled([getTasks(), getProjects()]);
    const t = tRes.status === "fulfilled" ? tRes.value : [];
    const p = pRes.status === "fulfilled" ? pRes.value : [];
    setTasks(t);
    setProjects(p);
    setEvents(buildCalendarEvents({ googleEvents, tasks: t, projects: p }));
    if (!quiet) setLoading(false);
  };

  useEffect(() => {
    loadAll();
    const onFocus = () => loadAll(true);
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  const step = (dir) => {
    setAnchor((prev) => {
      if (view === "week") return addDays(prev, 7 * dir);
      if (view === "day") return addDays(prev, dir);
      return new Date(prev.getFullYear(), prev.getMonth() + dir, 1);
    });
  };

  const openEvent = (event, trigger) => {
    eventTriggerRef.current = trigger || null;
    setSelectedEvent(event);
    setDrawer("event");
  };

  const selectDay = (day) => {
    setAnchor(day);
    setView("day");
  };

  const loadPlan = async () => {
    setPlanLoading(true);
    setPlanError(false);
    setStale(false);
    setPendingFreshPlan(null);
    try {
      setPlan(await getPlanningDay());
    } catch {
      setPlanError(true);
    } finally {
      setPlanLoading(false);
    }
  };

  const openPlan = () => {
    setDrawer("plan");
    if (!plan && !planLoading && !planError) loadPlan();
  };

  const prefillChat = () => {
    const request = "I've reviewed today's plan in the Calendar workspace. Please apply today's day plan to my Google Calendar and schedule the planned blocks.";
    let messages = [];
    try {
      const stored = sessionStorage.getItem(CHAT_STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) messages = parsed;
      }
    } catch {}
    messages.push({ role: "user", content: request });
    try {
      sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages));
    } catch {}
    navigate("/chat");
  };

  const handleSchedule = async () => {
    if (checkingSchedule) return;
    setCheckingSchedule(true);
    try {
      const fresh = await getPlanningDay();
      if (plan && planSignature(fresh) !== planSignature(plan)) {
        setPendingFreshPlan(fresh);
        setStale(true);
      } else {
        prefillChat();
      }
    } catch {
      setPlanError(true);
    } finally {
      setCheckingSchedule(false);
    }
  };

  const reviewUpdated = () => {
    setPlan(pendingFreshPlan);
    setPendingFreshPlan(null);
    setStale(false);
  };

  const connError = loadError || eventsError;
  const week = weekRange(anchor);

  return (
    <div className="page">
      <header className="calendar-header">
        <h2>Calendar</h2>
        <p className="calendar-header__sub">Your schedule, tasks, and available time.</p>
      </header>

      <CalendarConnectionState
        status={status}
        loading={loading}
        error={connError}
        onRetry={() => loadAll()}
      />

      <CalendarToolbar
        view={view}
        onViewChange={setView}
        anchor={anchor}
        onPrev={() => step(-1)}
        onNext={() => step(1)}
        onToday={() => setAnchor(new Date())}
        onPlanDay={openPlan}
        planBtnRef={planBtnRef}
      />

      {loading ? (
        <div className="calendar-skeleton" aria-busy="true">
          {[0, 1, 2, 3].map((i) => <OrbitSkeleton key={i} width="100%" height={56} />)}
        </div>
      ) : (
        <>
          {view === "month" ? (
            <CalendarMonthView
              anchor={anchor}
              events={events}
              onSelect={openEvent}
              onSelectDay={selectDay}
            />
          ) : view === "day" ? (
            <CalendarDayView date={anchor} events={events} onSelect={openEvent} />
          ) : (
            <CalendarGrid days={[week.start, ...Array.from({ length: 6 }, (_, i) => addDays(week.start, i + 1))]} events={events} onSelect={openEvent} />
          )}
        </>
      )}

      {drawer === "event" && selectedEvent && (
        <CalendarEventDrawer
          event={selectedEvent}
          canWrite={Boolean(status?.google_calendar_can_write)}
          onClose={() => setDrawer(null)}
          onReload={() => loadAll(true)}
          onOpenTask={() => navigate("/tasks")}
          triggerRef={eventTriggerRef}
        />
      )}

      {drawer === "plan" && (
        <DayPlanPanel
          plan={plan}
          loading={planLoading}
          error={planError}
          onRetry={loadPlan}
          onClose={() => setDrawer(null)}
          onSchedule={handleSchedule}
          scheduling={checkingSchedule}
          stale={stale}
          onReviewUpdated={reviewUpdated}
          triggerRef={planBtnRef}
        />
      )}
    </div>
  );
}