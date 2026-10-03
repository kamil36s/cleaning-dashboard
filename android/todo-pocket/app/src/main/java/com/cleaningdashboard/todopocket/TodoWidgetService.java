package com.cleaningdashboard.todopocket;

import android.content.Context;
import android.content.Intent;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;
import java.util.ArrayList;
import java.util.List;

public final class TodoWidgetService extends RemoteViewsService {
    @Override public RemoteViewsFactory onGetViewFactory(Intent intent) { return new Rows(getApplicationContext()); }

    private static final class Rows implements RemoteViewsFactory {
        private final Context context;
        private final List<TodoData.Item> tasks = new ArrayList<>();
        private final List<TodoData.Item> shopping = new ArrayList<>();
        Rows(Context context) { this.context = context; }
        @Override public void onCreate() { onDataSetChanged(); }
        @Override public void onDataSetChanged() {
            tasks.clear(); shopping.clear();
            for (TodoData.Item item : TodoData.cached(context))
                (item.bucket.equals("shopping") ? shopping : tasks).add(item);
        }
        @Override public void onDestroy() { tasks.clear(); shopping.clear(); }
        @Override public int getCount() { return 2 + tasks.size() + shopping.size(); }
        @Override public RemoteViews getViewAt(int position) {
            if (position == 0 || position == tasks.size() + 1) {
                boolean taskSection = position == 0;
                RemoteViews section = new RemoteViews(context.getPackageName(), R.layout.todo_widget_section);
                section.setTextViewText(R.id.section_text,
                    (taskSection ? "TASKI  " + tasks.size() : "ZAKUPY  " + shopping.size()));
                return section;
            }
            TodoData.Item item = position <= tasks.size()
                ? tasks.get(position - 1) : shopping.get(position - tasks.size() - 2);
            RemoteViews row = new RemoteViews(context.getPackageName(), R.layout.todo_widget_item);
            row.setTextViewText(R.id.item_text, "○  " + item.title);
            row.setOnClickFillInIntent(R.id.item_text, new Intent().putExtra("id", item.id));
            return row;
        }
        @Override public RemoteViews getLoadingView() { return null; }
        @Override public int getViewTypeCount() { return 2; }
        @Override public long getItemId(int position) { return position; }
        @Override public boolean hasStableIds() { return false; }
    }
}
