package com.cleaningdashboard.todopocket;

import android.app.Activity;
import android.app.AlertDialog;
import android.appwidget.AppWidgetManager;
import android.content.ComponentName;
import android.os.Bundle;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int INK = Color.rgb(238, 243, 235), MUTED = Color.rgb(139, 155, 141);
    private static final int GREEN = Color.rgb(170, 209, 169), BG = Color.rgb(15, 21, 17);
    private static final int SURFACE = Color.rgb(27, 36, 29);
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private String bucket = "now";
    private LinearLayout list, root;
    private TextView status, taskTab, shopTab;
    private EditText input;
    private List<TodoData.Item> items;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(BG); getWindow().setNavigationBarColor(BG);
        getWindow().getDecorView().setSystemUiVisibility(0);
        items = TodoData.cached(this);
        build();
        TodoWidget.schedule(this);
        if (TodoData.url(this).isEmpty()) showSettings(); else refresh();
    }
    @Override protected void onDestroy() { network.shutdown(); super.onDestroy(); }
    private int dp(float value) { return (int) (value * getResources().getDisplayMetrics().density + .5f); }
    private GradientDrawable shape(int color, int radius) {
        GradientDrawable d = new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(radius)); return d;
    }
    private TextView text(String content, int size, int color, boolean bold) {
        TextView view = new TextView(this); view.setText(content); view.setTextSize(size); view.setTextColor(color);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setGravity(Gravity.CENTER_VERTICAL); return view;
    }
    private void build() {
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(BG);
        root.setPadding(dp(22), dp(26), dp(22), dp(20)); setContentView(root);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(android.view.WindowInsets.Type.systemBars());
                root.setPadding(dp(22) + bars.left, dp(26) + bars.top, dp(22) + bars.right, dp(20) + bars.bottom);
            } else {
                root.setPadding(dp(22), dp(26) + insets.getSystemWindowInsetTop(), dp(22),
                    dp(20) + insets.getSystemWindowInsetBottom());
            }
            return insets;
        });
        LinearLayout header = new LinearLayout(this); header.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout heading = new LinearLayout(this); heading.setOrientation(LinearLayout.VERTICAL);
        heading.addView(text("To-do", 31, INK, true));
        heading.addView(text("Tylko otwarte rzeczy", 13, MUTED, false));
        header.addView(heading, new LinearLayout.LayoutParams(0, dp(64), 1));
        TextView refresh = text("↻", 29, GREEN, false); refresh.setGravity(Gravity.CENTER);
        header.addView(refresh, new LinearLayout.LayoutParams(dp(42), dp(42))); refresh.setOnClickListener(v -> refresh());
        TextView settings = text("⚙", 22, GREEN, false); settings.setGravity(Gravity.CENTER);
        header.addView(settings, new LinearLayout.LayoutParams(dp(42), dp(42))); settings.setOnClickListener(v -> showSettings());
        root.addView(header);
        LinearLayout tabs = new LinearLayout(this); tabs.setPadding(0, dp(26), 0, dp(12));
        taskTab = tab("Taski", "now"); shopTab = tab("Zakupy", "shopping");
        tabs.addView(taskTab, new LinearLayout.LayoutParams(0, dp(44), 1));
        LinearLayout.LayoutParams shopParams = new LinearLayout.LayoutParams(0, dp(44), 1); shopParams.leftMargin = dp(8);
        tabs.addView(shopTab, shopParams); root.addView(tabs);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        list = new LinearLayout(this); list.setOrientation(LinearLayout.VERTICAL); list.setPadding(0, dp(10), 0, dp(20));
        scroll.addView(list); root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        status = text("", 12, MUTED, false); status.setGravity(Gravity.CENTER);
        root.addView(status, new LinearLayout.LayoutParams(-1, dp(32)));
        LinearLayout add = new LinearLayout(this); add.setGravity(Gravity.CENTER_VERTICAL);
        add.setBackground(shape(SURFACE, 18)); add.setPadding(dp(14), 0, dp(6), 0);
        input = new EditText(this); input.setTextSize(15); input.setTextColor(INK); input.setSingleLine(true);
        input.setHintTextColor(MUTED); input.setBackgroundColor(Color.TRANSPARENT); input.setHint("Dodaj zadanie");
        add.addView(input, new LinearLayout.LayoutParams(0, dp(56), 1));
        TextView plus = text("+", 29, BG, false); plus.setGravity(Gravity.CENTER);
        plus.setBackground(shape(GREEN, 15)); add.addView(plus, new LinearLayout.LayoutParams(dp(44), dp(44)));
        plus.setOnClickListener(v -> addItem());
        root.addView(add);
        render();
    }
    private TextView tab(String title, String id) {
        TextView view = text(title, 14, INK, true); view.setGravity(Gravity.CENTER);
        view.setOnClickListener(v -> { bucket = id; input.setHint(id.equals("now") ? "Dodaj zadanie" : "Dodaj zakup"); render(); });
        return view;
    }
    private void render() {
        taskTab.setBackground(shape(bucket.equals("now") ? SURFACE : Color.TRANSPARENT, 14));
        shopTab.setBackground(shape(bucket.equals("shopping") ? SURFACE : Color.TRANSPARENT, 14));
        list.removeAllViews(); int count = 0;
        for (TodoData.Item item : items) if (item.bucket.equals(bucket)) {
            count++;
            LinearLayout row = new LinearLayout(this); row.setGravity(Gravity.CENTER_VERTICAL);
            TextView check = text("○", 26, GREEN, false); check.setGravity(Gravity.CENTER);
            row.addView(check, new LinearLayout.LayoutParams(dp(44), dp(54)));
            TextView title = text(item.title, 16, INK, false);
            title.setMaxLines(2); row.addView(title, new LinearLayout.LayoutParams(0, dp(54), 1));
            row.setOnClickListener(v -> complete(item));
            list.addView(row);
            View line = new View(this); line.setBackgroundColor(Color.rgb(42, 53, 44));
            list.addView(line, new LinearLayout.LayoutParams(-1, dp(1)));
        }
        if (count == 0) {
            TextView empty = text(bucket.equals("now") ? "Wszystko zrobione ✨" : "Lista zakupów jest pusta", 15, MUTED, false);
            empty.setGravity(Gravity.CENTER); list.addView(empty, new LinearLayout.LayoutParams(-1, dp(160)));
        }
    }
    private interface Operation { List<TodoData.Item> run() throws Exception; }
    private void execute(Operation operation) {
        status.setText("Synchronizuję…");
        network.execute(() -> {
            try {
                List<TodoData.Item> next = operation.run();
                runOnUiThread(() -> { items = next; render(); status.setText("Zsynchronizowano"); });
            } catch (Exception e) {
                runOnUiThread(() -> status.setText(e.getMessage() == null ? "Brak połączenia" : e.getMessage()));
            }
        });
    }
    private void refresh() { execute(() -> TodoApi.refresh(this)); }
    private void complete(TodoData.Item item) { execute(() -> TodoApi.complete(this, item.id)); }
    private void addItem() {
        String title = input.getText().toString().trim(); if (title.isEmpty()) return;
        String target = bucket; input.setText("");
        ((InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(input.getWindowToken(), 0);
        execute(() -> TodoApi.add(this, title, target));
    }
    private void showSettings() {
        LinearLayout form = new LinearLayout(this); form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(22), dp(8), dp(22), 0);
        EditText url = new EditText(this); url.setSingleLine(true); url.setTextSize(15);
        url.setHint("http://adres-komputera:8000"); url.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        url.setText(TodoData.url(this)); form.addView(url);
        EditText token = new EditText(this); token.setSingleLine(true); token.setTextSize(15);
        token.setHint("Token synchronizacji"); token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        token.setText(TodoData.token(this)); form.addView(token);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("Połącz z dashboardem")
            .setView(form).setNeutralButton("Dodaj widżet", (ignored, button) -> pinWidget())
            .setNegativeButton("Anuluj", null).setPositiveButton("Zapisz", null).create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            try {
                TodoData.saveConfig(this, url.getText().toString(), token.getText().toString());
                dialog.dismiss(); refresh();
            } catch (Exception e) { url.setError(e.getMessage()); }
        }));
        dialog.show();
    }
    private void pinWidget() {
        AppWidgetManager manager = AppWidgetManager.getInstance(this);
        if (android.os.Build.VERSION.SDK_INT >= 26 && manager.isRequestPinAppWidgetSupported()) {
            manager.requestPinAppWidget(new ComponentName(this, TodoWidget.class), null, null);
        } else {
            Toast.makeText(this, "Przytrzymaj ekran główny → Widżety → Taski", Toast.LENGTH_LONG).show();
        }
    }
}
