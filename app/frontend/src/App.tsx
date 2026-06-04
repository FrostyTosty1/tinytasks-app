import { useEffect, useRef, useState } from "react";
import type { Dispatch, FormEvent, SetStateAction } from "react";

import {
  createTask,
  deleteTask,
  fetchTasks,
  toggleTaskDone,
  updateTaskTitle,
  type Task,
} from "./api";

export default function App() {
  // Main UI state:
  // - loading: initial data is still being fetched
  // - error: last user-visible error message
  // - tasks: tasks received from the backend
  // - newTitle: text from the "new task" input field
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [newTitle, setNewTitle] = useState("");

  // Inline edit state for one task at a time:
  // - editingId: which task is currently being edited
  // - editingTitle: current text inside the edit input
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  // Pending operation flags.
  // These help prevent duplicate clicks while a request is already in flight.
  const [adding, setAdding] = useState(false);
  const [pendingToggle, setPendingToggle] = useState<Set<string>>(new Set());
  const [pendingDelete, setPendingDelete] = useState<Set<string>>(new Set());
  const [pendingSave, setPendingSave] = useState<Set<string>>(new Set());

  // Client-side filter for the already loaded task list.
  const [filter, setFilter] = useState<"all" | "open" | "done">("all");

  // Dark mode preference:
  // 1) first try localStorage
  // 2) otherwise fall back to the OS/browser preference
  const [dark, setDark] = useState<boolean>(() => {
    const saved = localStorage.getItem("tt.dark");
    if (saved === "true") return true;
    if (saved === "false") return false;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  });

  // Visual state used only for CSS animations:
  // - appeared: tasks that have already finished the "appear" animation
  // - deletingVisual: tasks that are currently fading out before removal
  const [appeared, setAppeared] = useState<Set<string>>(new Set());
  const [deletingVisual, setDeletingVisual] = useState<Set<string>>(new Set());

  // Store delete-animation timers so they can be cleared on unmount.
  const deleteTimeoutsRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    const deleteTimeouts = deleteTimeoutsRef.current;

    return () => {
      // Clear pending delete timers when the component unmounts
      // to avoid updating state after the component is gone.
      for (const t of deleteTimeouts) {
        window.clearTimeout(t);
      }
      deleteTimeouts.clear();
    };
  }, []);

  useEffect(() => {
    // Load tasks once, when the component is mounted for the first time.
    fetchTasks()
      .then(setTasks)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    // Keep the <html> element and localStorage in sync with the current theme.
    const root = document.documentElement;
    if (dark) root.classList.add("dark");
    else root.classList.remove("dark");
    localStorage.setItem("tt.dark", String(dark));
  }, [dark]);

  useEffect(() => {
    // Any task that is present in `tasks` but missing from `appeared`
    // is treated as "new" for animation purposes.
    const idsToSchedule: string[] = [];
    for (const t of tasks) {
      if (!appeared.has(t.id)) idsToSchedule.push(t.id);
    }

    if (idsToSchedule.length > 0) {
      // Wait one tick so the initial hidden classes are rendered first,
      // then mark the tasks as appeared and let CSS animate them in.
      const t = window.setTimeout(() => {
        setAppeared((prev) => {
          const next = new Set(prev);
          idsToSchedule.forEach((id) => next.add(id));
          return next;
        });
      }, 0);

      return () => window.clearTimeout(t);
    }
  }, [tasks, appeared]);

  // Helper for operations tracked by task id.
  // It adds the id to a Set before the async work starts,
  // and removes it when the work finishes.
  function withId<T extends string>(
    setState: Dispatch<SetStateAction<Set<T>>>,
    id: T,
    fn: () => Promise<void>
  ) {
    setState((prev) => new Set(prev).add(id));
    return fn().finally(() => {
      setState((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    });
  }

  // Create a new task from the form input.
  async function handleAddTask(e: FormEvent) {
    e.preventDefault();

    const title = newTitle.trim();
    if (!title || adding) return; // Ignore empty input and duplicate submits.

    setError(null);
    setAdding(true);

    try {
      const created = await createTask(title);

      // Add the new task locally instead of re-fetching the whole list.
      setTasks((prev) => [created, ...prev]);

      // Clear the input after successful creation.
      setNewTitle("");

      // Remove the id from `appeared` so the new item can run its
      // appear animation on the next effect pass.
      setAppeared((prev) => {
        const next = new Set(prev);
        next.delete(created.id);
        return next;
      });
    } catch (err) {
      console.error(err);
      setError("Failed to create task");
    } finally {
      setAdding(false);
    }
  }

  // Toggle the "done" state of a task.
  async function handleToggle(task: Task) {
    if (pendingToggle.has(task.id)) return; // Prevent duplicate requests.

    setError(null);

    await withId(setPendingToggle, task.id, async () => {
      try {
        const updated = await toggleTaskDone(task.id, !task.done);

        // Replace only the updated task in the current list.
        setTasks((prev) => prev.map((t) => (t.id === task.id ? updated : t)));
      } catch (err) {
        console.error(err);
        setError("Failed to update task status");
      }
    });
  }

  // Delete a task.
  // Removal from the list is delayed a bit so the fade-out animation can play first.
  async function handleDelete(task: Task) {
    if (pendingDelete.has(task.id)) return;
    if (!confirm(`Delete task "${task.title}"?`)) return;

    setError(null);

    // Save whether this task was being edited before the async work starts.
    // This avoids relying on state later inside the timeout callback.
    const wasEditingThis = editingId === task.id;

    await withId(setPendingDelete, task.id, async () => {
      try {
        await deleteTask(task.id);

        // If the deleted task was in edit mode, clear edit state immediately.
        if (wasEditingThis) {
          setEditingId(null);
          setEditingTitle("");
        }

        // Start the visual fade-out before actually removing the item from state.
        setDeletingVisual((prev) => new Set(prev).add(task.id));

        // Remove the task after the CSS transition finishes.
        const t = window.setTimeout(() => {
          setTasks((prev) => prev.filter((t) => t.id !== task.id));

          setDeletingVisual((prev) => {
            const next = new Set(prev);
            next.delete(task.id);
            return next;
          });

          // Also remove the id from the appear-tracking set
          // because this task no longer exists in the list.
          setAppeared((prev) => {
            const next = new Set(prev);
            next.delete(task.id);
            return next;
          });

          // Delete the timer id from the registry after it has fired.
          deleteTimeoutsRef.current.delete(t);
        }, 180); // Keep this in sync with the CSS transition duration.

        // Remember the timer so it can be cleared on unmount.
        deleteTimeoutsRef.current.add(t);
      } catch (err) {
        console.error(err);
        setError("Failed to delete task");
      }
    });
  }

  // Enter inline edit mode for one task.
  function startEdit(task: Task) {
    setEditingId(task.id);
    setEditingTitle(task.title);
  }

  // Leave inline edit mode without saving changes.
  function cancelEdit() {
    setEditingId(null);
    setEditingTitle("");
  }

  // Save the edited task title.
  async function saveEdit(task: Task) {
    const title = editingTitle.trim();
    if (!title || pendingSave.has(task.id)) return; // Ignore empty titles and duplicate saves.

    setError(null);

    await withId(setPendingSave, task.id, async () => {
      try {
        const updated = await updateTaskTitle(task.id, title);

        // Replace only the updated task and exit edit mode.
        setTasks((prev) => prev.map((t) => (t.id === task.id ? updated : t)));
        setEditingId(null);
        setEditingTitle("");
      } catch (err) {
        console.error(err);
        setError("Failed to update title");
      }
    });
  }

  if (loading) return <div className="p-4">Loading…</div>;

  // Apply the selected filter before rendering the list.
  const visibleTasks = tasks.filter((t) =>
    filter === "all" ? true : filter === "done" ? t.done : !t.done
  );

  return (
    <div className="min-h-screen flex justify-center bg-gray-50 text-gray-900 dark:bg-gray-900 dark:text-gray-100">
      <div className="mx-auto w-full max-w-2xl px-6 py-10 font-sans rounded-xl shadow-lg bg-white dark:bg-gray-800">
        {error && (
          <div className="mb-4 flex items-center justify-between rounded-md border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-800 dark:border-red-700 dark:bg-red-900/30 dark:text-red-200">
            <span>{error}</span>
            <button
              onClick={() => setError(null)}
              className="ml-4 text-red-700 hover:underline dark:text-red-200"
              title="Dismiss error"
            >
              Dismiss
            </button>
          </div>
        )}

        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">TinyTasks</h1>

          {/* Toggle the persisted dark/light theme. */}
          <button
            onClick={() => setDark((d) => !d)}
            className={`rounded-md px-3 py-1.5 text-sm transition focus:outline-none focus:ring-2 ${
              dark
                ? "bg-amber-500 text-white hover:bg-amber-600 focus:ring-amber-300"
                : "bg-gray-200 text-gray-900 hover:bg-gray-300 focus:ring-gray-300"
            }`}
            title="Toggle dark mode"
          >
            {dark ? "Dark: ON" : "Dark: OFF"}
          </button>
        </div>

        {/* Filter buttons for the already loaded tasks. */}
        <div className="mb-4 flex gap-2">
          <button
            onClick={() => setFilter("all")}
            className={`rounded-md px-3 py-1.5 text-sm transition ${
              filter === "all"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-900 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
            }`}
          >
            All
          </button>
          <button
            onClick={() => setFilter("open")}
            className={`rounded-md px-3 py-1.5 text-sm transition ${
              filter === "open"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-900 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
            }`}
          >
            Open
          </button>
          <button
            onClick={() => setFilter("done")}
            className={`rounded-md px-3 py-1.5 text-sm transition ${
              filter === "done"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-900 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
            }`}
          >
            Done
          </button>
        </div>

        {/* Form for creating a new task. */}
        <form onSubmit={handleAddTask} className="mb-4 flex gap-2">
          <input
            type="text"
            placeholder="New task title"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            maxLength={140}
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 dark:border-gray-700 dark:bg-gray-800 dark:placeholder-gray-400"
          />
          <button
            type="submit"
            disabled={adding || !newTitle.trim()}
            className={`rounded-md px-4 py-2 text-white transition focus:outline-none focus:ring-2 ${
              adding
                ? "bg-blue-300 cursor-wait"
                : "bg-blue-600 hover:bg-blue-700 focus:ring-blue-300"
            }`}
          >
            {adding ? "Adding…" : "Add"}
          </button>
        </form>

        {visibleTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center text-gray-600 dark:text-gray-400">
            {/* Simple empty-state icon. */}
            <div className="text-6xl mb-3">{tasks.length === 0 ? "📝" : "🎉"}</div>

            {tasks.length === 0 ? (
              <>
                <p className="text-lg font-medium mb-1">No tasks yet</p>
                <p className="text-sm text-gray-500 dark:text-gray-500">
                  Add your first one above to get started.
                </p>
              </>
            ) : (
              <>
                <p className="text-lg font-medium mb-1">All tasks completed!</p>
                <p className="text-sm text-gray-500 dark:text-gray-500">
                  Take a break, you deserve it ☕
                </p>
              </>
            )}
          </div>
        ) : (
          <ul className="space-y-2">
            {visibleTasks.map((t) => {
              const isEditing = editingId === t.id;
              const isToggling = pendingToggle.has(t.id);
              const isDeleting = pendingDelete.has(t.id);
              const isSaving = pendingSave.has(t.id);

              // Flags used only for CSS animation classes.
              const isAppeared = appeared.has(t.id);
              const isFadingOut = deletingVisual.has(t.id);

              return (
                <li
                  key={t.id}
                  className={`flex items-center justify-between gap-2 rounded-lg border p-3
                    border-gray-200 dark:border-gray-700
                    transition-all duration-200
                    ${
                      t.done
                        ? "bg-emerald-50 dark:bg-emerald-900/20"
                        : "bg-white dark:bg-gray-800"
                    }
                    ${
                      isAppeared
                        ? "opacity-100 translate-y-0"
                        : "opacity-0 translate-y-2"
                    }
                    ${
                      isFadingOut ? "opacity-0 scale-[0.98] translate-y-1" : ""
                    }
                  `}
                >
                  <span className="min-w-0">
                    {isEditing ? (
                      <input
                        autoFocus
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        maxLength={140}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") saveEdit(t);
                          if (e.key === "Escape") cancelEdit();
                        }}
                        className="min-w-[220px] rounded-md border px-2 py-1 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 border-gray-300 dark:border-gray-700 dark:bg-gray-900"
                        placeholder="Edit title"
                      />
                    ) : (
                      <strong className="truncate">{t.title}</strong>
                    )}
                    <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
                      {t.done ? "done" : "open"}
                    </span>
                  </span>

                  <div className="flex items-center gap-2">
                    {isEditing ? (
                      <>
                        <button
                          onClick={() => saveEdit(t)}
                          disabled={isSaving}
                          className={`rounded-md px-3 py-1.5 transition focus:outline-none focus:ring-2 ${
                            isSaving
                              ? "bg-blue-300 text-white cursor-wait"
                              : "bg-blue-600 text-white hover:bg-blue-700 focus:ring-blue-300"
                          }`}
                          title="Save title"
                        >
                          {isSaving ? "Saving…" : "Save"}
                        </button>
                        <button
                          onClick={cancelEdit}
                          disabled={isSaving}
                          className={`rounded-md px-3 py-1.5 transition focus:outline-none focus:ring-2 ${
                            isSaving
                              ? "bg-gray-200 text-gray-400 cursor-not-allowed"
                              : "bg-gray-200 text-gray-900 hover:bg-gray-300 focus:ring-gray-300 dark:bg-gray-700 dark:text-gray-100 dark:hover:bg-gray-600"
                          }`}
                          title="Cancel editing"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={() => startEdit(t)}
                        className="rounded-md bg-amber-500 px-3 py-1.5 text-white transition hover:bg-amber-600 focus:outline-none focus:ring-2 focus:ring-amber-300"
                        title="Edit title"
                      >
                        Edit
                      </button>
                    )}

                    <button
                      onClick={() => handleToggle(t)}
                      disabled={isToggling || isFadingOut}
                      className={`rounded-md px-3 py-1.5 transition focus:outline-none focus:ring-2 ${
                        isToggling
                          ? "bg-gray-200 text-gray-400 cursor-wait"
                          : t.done
                            ? "bg-gray-200 text-gray-900 hover:bg-gray-300 focus:ring-gray-300 dark:bg-gray-700 dark:text-gray-100 dark:hover:bg-gray-600"
                            : "bg-emerald-600 text-white hover:bg-emerald-700 focus:ring-emerald-300"
                      }`}
                      title={t.done ? "Undo" : "Mark as done"}
                    >
                      {isToggling ? "Saving…" : t.done ? "Undo" : "Done"}
                    </button>

                    <button
                      onClick={() => handleDelete(t)}
                      disabled={isDeleting || isFadingOut}
                      className={`rounded-md px-3 py-1.5 transition focus:outline-none focus:ring-2 ${
                        isDeleting || isFadingOut
                          ? "bg-red-300 text-white cursor-wait"
                          : "bg-red-600 text-white hover:bg-red-700 focus:ring-red-300"
                      }`}
                      title="Delete task"
                    >
                      {isDeleting ? "Deleting…" : "Delete"}
                    </button>

                    <span className="hidden text-xs text-gray-400 sm:inline">
                      {new Date(t.created_at).toLocaleString()}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}