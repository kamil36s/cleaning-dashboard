package com.cleaningdashboard.companion

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    private lateinit var queue: ReceiptQueue
    private lateinit var baseUrl: EditText
    private lateinit var pairingToken: EditText
    private lateinit var connectionState: TextView
    private lateinit var history: LinearLayout
    private lateinit var barcodeResult: TextView

    private val openDocument = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { previewAndQueue(it, contentResolver.getType(it)) }
    }

    private val documentLauncher = registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { activityResult ->
        if (activityResult.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val result = GmsDocumentScanningResult.fromActivityResultIntent(activityResult.data) ?: return@registerForActivityResult
        previewAndQueueScan(result)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        queue = ReceiptQueue(this)
        setContentView(buildUi())
        loadConfig()
        handleIncomingIntent(intent)
        refresh()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun buildUi(): ScrollView {
        val scroll = ScrollView(this)
        val root = vertical(18).apply { setPadding(28, 34, 28, 50) }
        root.addView(title("Dashboard Companion", 26f))
        connectionState = title("Offline", 15f).also { root.addView(it) }

        root.addView(section("Połączenie z lokalnym Dashboardem"))
        baseUrl = field("Adres, np. http://komputer.local:8000").also { root.addView(it) }
        pairingToken = field("Token parowania").also { input -> input.inputType = 0x00000081; root.addView(input) }
        root.addView(row(
            button("Zapisz konfigurację") { saveConfig() },
            button("Testuj") { testConnection() },
            button("Resetuj") { CompanionConfig.reset(this); loadConfig(); refresh() },
        ))

        root.addView(section("Paragony"))
        root.addView(row(
            button("Skanuj dokument") { startDocumentScanner() },
            button("Importuj plik") { openDocument.launch(arrayOf("application/pdf", "application/json", "text/json", "image/jpeg", "image/png", "image/webp")) },
            button("Synchronizuj") { CompanionSync.retry(this); refreshSoon() },
        ))

        root.addView(section("Skaner produktu"))
        root.addView(button("Skanuj EAN / UPC") { scanBarcode() })
        barcodeResult = TextView(this).apply { text = "Brak zeskanowanego kodu"; setPadding(0, 12, 0, 8) }
        root.addView(barcodeResult)

        root.addView(section("Historia wysyłania"))
        history = vertical(8).also { root.addView(it) }
        scroll.addView(root)
        return scroll
    }

    private fun vertical(spacing: Int) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        dividerPadding = spacing
        layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    }

    private fun row(vararg views: Button) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.START
        views.forEach { view -> addView(view, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { setMargins(0, 4, 8, 4) }) }
    }

    private fun title(text: String, size: Float) = TextView(this).apply { this.text = text; textSize = size; setPadding(0, 6, 0, 8) }
    private fun section(text: String) = title(text, 18f).apply { setPadding(0, 28, 0, 8) }
    private fun field(hint: String) = EditText(this).apply { this.hint = hint; setSingleLine(true) }
    private fun button(text: String, action: () -> Unit) = Button(this).apply { this.text = text; setOnClickListener { action() } }

    private fun loadConfig() {
        val config = CompanionConfig.load(this)
        baseUrl.setText(config.baseUrl)
        pairingToken.setText(config.token)
    }

    private fun saveConfig() {
        try {
            CompanionConfig.save(this, baseUrl.text.toString(), pairingToken.text.toString())
            Toast.makeText(this, "Konfiguracja zapisana", Toast.LENGTH_SHORT).show()
            testConnection()
        } catch (error: IllegalArgumentException) {
            connectionState.text = error.message
        }
    }

    private fun testConnection() {
        val config = CompanionConfig.load(this)
        lifecycleScope.launch {
            val connected = withContext(Dispatchers.IO) { runCatching { DashboardClient.status(config) }.getOrDefault(false) }
            connectionState.text = if (connected) "Connected" else "Offline"
        }
    }

    private fun startDocumentScanner() {
        val options = GmsDocumentScannerOptions.Builder()
            .setGalleryImportAllowed(true)
            .setPageLimit(8)
            .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_JPEG, GmsDocumentScannerOptions.RESULT_FORMAT_PDF)
            .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL)
            .build()
        GmsDocumentScanning.getClient(options).getStartScanIntent(this)
            .addOnSuccessListener { sender -> documentLauncher.launch(IntentSenderRequest.Builder(sender).build()) }
            .addOnFailureListener { error -> showError(error.message ?: "Skaner dokumentów jest niedostępny") }
    }

    private fun scanBarcode() {
        val options = GmsBarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_EAN_13, Barcode.FORMAT_EAN_8, Barcode.FORMAT_UPC_A, Barcode.FORMAT_UPC_E)
            .enableAutoZoom()
            .build()
        GmsBarcodeScanning.getClient(this, options).startScan()
            .addOnSuccessListener { barcode -> barcode.rawValue?.let(::lookupBarcode) ?: showError("Kod nie zawiera wartości") }
            .addOnFailureListener { error -> showError(error.message ?: "Skanowanie nie powiodło się") }
    }

    private fun lookupBarcode(barcode: String) {
        barcodeResult.text = barcode
        val config = CompanionConfig.load(this)
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { runCatching { DashboardClient.lookupBarcode(config, barcode) } }
            result.onSuccess { product ->
                if (product.known) barcodeResult.text = "$barcode\n${product.name}\n${product.category ?: "bez kategorii"}"
                else showUnknownBarcode(barcode)
            }.onFailure { showError(it.message ?: "Nie można połączyć z Dashboardem") }
        }
    }

    private fun showUnknownBarcode(barcode: String) {
        val name = field("Opcjonalna nazwa produktu")
        AlertDialog.Builder(this)
            .setTitle("Produkt nieznany")
            .setMessage(barcode)
            .setView(name)
            .setPositiveButton("Zapisz oczekujący") { _, _ -> savePendingBarcode(barcode, name.text.toString()) }
            .setNeutralButton("Skanuj ponownie") { _, _ -> scanBarcode() }
            .setNegativeButton("Anuluj", null)
            .show()
    }

    private fun savePendingBarcode(barcode: String, name: String) {
        val config = CompanionConfig.load(this)
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { runCatching { DashboardClient.savePendingBarcode(config, barcode, name) } }
            result.onSuccess { barcodeResult.text = "$barcode\n${it.name}\nOczekuje na uzupełnienie" }
                .onFailure { showError(it.message ?: "Nie udało się zapisać produktu") }
        }
    }

    private fun handleIncomingIntent(intent: Intent) {
        val uri = IncomingIntentPolicy.uri(intent)
        uri?.let { previewAndQueue(it, intent.type) }
    }

    private fun previewAndQueue(uri: Uri, mimeType: String?) {
        if (!ReceiptTypePolicy.isSupported(mimeType ?: contentResolver.getType(uri))) {
            showError("Nieobsługiwany typ pliku")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Dodać paragon?")
            .setMessage("Typ: ${mimeType ?: contentResolver.getType(uri)}\nPlik zostanie skopiowany do prywatnej kolejki aplikacji.")
            .setPositiveButton("Dodaj i wyślij") { _, _ ->
                runCatching { queue.enqueue(uri, mimeType) }
                    .onSuccess { item -> prepareOcrAndSchedule(item); refresh() }
                    .onFailure { showError(it.message ?: "Nie można odczytać pliku") }
            }
            .setNegativeButton("Anuluj", null)
            .show()
    }

    private fun previewAndQueueScan(result: GmsDocumentScanningResult) {
        val pages = result.pages.orEmpty().map { it.imageUri }
        val pdf = result.pdf?.uri
        if (pages.isEmpty() && pdf == null) {
            showError("Skan nie zawiera stron")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Dodać zeskanowany paragon?")
            .setMessage("Strony: ${pages.size}\nPDF: ${if (pdf != null) "tak" else "nie"}\nObrazy posłużą do OCR, a PDF zostanie zachowany jako źródło.")
            .setPositiveButton("Dodaj i wyślij") { _, _ ->
                runCatching { queue.enqueueScan(pages, pdf) }
                    .onSuccess { item -> prepareOcrAndSchedule(item); refresh() }
                    .onFailure { showError(it.message ?: "Nie można zapisać skanu") }
            }
            .setNegativeButton("Anuluj", null)
            .show()
    }

    private fun prepareOcrAndSchedule(item: QueueItem) {
        if (!item.mimeType.startsWith("image/") && item.attachments.none { it.sourceRole == "page" }) {
            CompanionSync.schedule(this)
            return
        }
        connectionState.text = "OCR na urządzeniu…"
        ReceiptOcr.recognize(this, item) { evidence ->
            queue.updateOcr(item.id, evidence)
            CompanionSync.schedule(this)
            refresh()
        }
    }

    private fun refreshSoon() {
        refresh()
        history.postDelayed({ refresh() }, 1_500)
    }

    private fun refresh() {
        val items = queue.list()
        val pending = items.count { it.state != UploadState.UPLOADED }
        connectionState.text = if (!CompanionConfig.load(this).configured) "Offline · skonfiguruj serwer" else if (pending > 0) "Sync pending: $pending" else "Gotowe"
        history.removeAllViews()
        if (items.isEmpty()) history.addView(TextView(this).apply { text = "Brak importów" })
        items.forEach { item ->
            history.addView(TextView(this).apply {
                text = "${item.filename}\n${item.state.name.lowercase()}${item.serverReceiptId?.let { " · $it" } ?: ""}${item.resultSummary?.let { "\n$it" } ?: ""}${item.lastError?.let { " · $it" } ?: ""}"
                setPadding(0, 10, 0, 10)
            })
        }
    }

    private fun showError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }
}
