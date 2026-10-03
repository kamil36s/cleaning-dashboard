# Habits reminders

Habits, medications, and supplements can carry a user-configured reminder schedule. The scheduler never derives a schedule, dose, or timing from an item's name or category.

Recurring dates and clock times use the browser's local calendar and timezone. Global time groups are resolved when occurrences are calculated, so editing a group changes all future dependent reminders. Interval schedules use the configured anchor date plus exact day multiples; they do not use odd/even calendar dates.

The browser claims each due occurrence through the Habits API before notifying. The durable occurrence key uses the item, local date, and schedule source, preventing duplicate alerts after reload and preventing a time-group edit from replaying an occurrence that already fired. A five-minute startup grace window allows only recently missed reminders.

Browser notification permission is requested only when the user explicitly enables browser notifications in reminder settings. Dashboard toasts continue when permission is denied or the Notifications API is unavailable.

## Reliability limitation

The dashboard has no general service worker or native background scheduler. Browser timers and Notifications API calls therefore run only while the dashboard is open (and may be throttled in a background tab). Closing the browser can prevent a reminder from firing; reopening it does not replay reminders missed by more than the grace window. A future native companion or server push worker would be required for closed-browser delivery.
