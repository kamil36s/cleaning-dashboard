export const CSC_SERVICE_UUID = 0x1816;
export const CSC_MEASUREMENT_UUID = 0x2a5b;
export const DEFAULT_WHEEL_CIRCUMFERENCE_MM = 2096;
export const CSC_INACTIVITY_MS = 2000;
export const CSC_STALE_GRACE_MS = 2000;
export const CSC_LAST_DEVICE_STORAGE_KEY = "liveWorkout.csc.lastDeviceId";
export const CSC_RECONNECT_DELAYS_MS = Object.freeze([1000, 2000, 4000, 8000, 15000]);
export const CSC_CONNECTION_TIMEOUT_MS = 12_000;

const CSC_EVENT_TICKS_PER_SECOND = 1024;
const UINT16_MODULUS = 0x1_0000;
const UINT32_MODULUS = 0x1_0000_0000;

export function cscDeviceRequestOptions() {
  // Some Magene sensors expose CSC only after the GATT connection and do not
  // advertise 0x1816. A service filter therefore hides a valid, awake sensor.
  return {
    acceptAllDevices: true,
    optionalServices: [CSC_SERVICE_UUID],
  };
}

export function formatCscConnectionError(error) {
  if (error?.name === "AbortError") return "Łączenie z czujnikiem zostało anulowane.";
  if (error?.name === "NotFoundError") {
    return "Nie wybrano czujnika. Zakręć korbą lub kołem, aby obudzić Magene, i spróbuj ponownie.";
  }
  if (error?.name === "NotSupportedError") {
    return "Web Bluetooth nie jest dostępny. Użyj Chrome lub Edge na HTTPS albo localhost.";
  }
  if (error?.name === "SecurityError") {
    return "Przeglądarka zablokowała Bluetooth. Otwórz dashboard przez HTTPS albo localhost i zezwól na dostęp.";
  }
  if (error?.code === "csc_service_missing") {
    return "Wybrane urządzenie nie udostępnia usługi Cycling Speed and Cadence (CSC). Wybierz czujnik Magene, nie smartwatch.";
  }
  if (error?.code === "csc_gatt_missing") {
    return "Wybrane urządzenie nie udostępnia połączenia Bluetooth GATT. Wybierz aktywny czujnik Magene.";
  }
  if (error?.code === "csc_characteristic_missing") {
    return "Czujnik nie udostępnia pomiaru CSC. Obudź go ruchem korby lub koła i połącz ponownie.";
  }
  if (error?.name === "TimeoutError") {
    return "Czujnik nie odpowiedział na czas. Obudź Magene, zbliż go do komputera i spróbuj ponownie.";
  }
  if (["NetworkError", "InvalidStateError"].includes(error?.name)) {
    return "Połączenie Bluetooth chwilowo zniknęło. Zakręć korbą lub kołem i zbliż Magene do komputera; ponawiam próbę.";
  }
  return error?.message || "Nie udało się połączyć z czujnikiem CSC.";
}

function connectionError(message, code, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.code = code;
  error.retryable = false;
  return error;
}

async function withTimeout(promise, timeoutMs, label) {
  let timeoutId;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      const error = new Error(`${label} przekroczyło limit czasu.`);
      error.name = "TimeoutError";
      reject(error);
    }, timeoutMs);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timeoutId);
  }
}

function isRetryableConnectionError(error) {
  return error?.retryable !== false && !["AbortError", "NotFoundError", "SecurityError", "NotSupportedError"].includes(error?.name);
}

function transientGattError(error, device) {
  if (["SecurityError", "NotSupportedError"].includes(error?.name)) return null;
  if (device?.gatt?.connected && !["NetworkError", "InvalidStateError"].includes(error?.name)) return null;
  if (error?.name === "NetworkError" || error?.name === "InvalidStateError") return error;
  const lost = new Error("Połączenie GATT zostało zerwane podczas odczytu CSC.", { cause: error });
  lost.name = "NetworkError";
  return lost;
}

function unsignedDelta(current, previous, modulus) {
  return (current - previous + modulus) % modulus;
}

function finiteNonNegative(value) {
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function selectMode({ hasWheel, hasCrank, wheelEventChanged, crankEventChanged, previousMode }) {
  if (hasWheel && !hasCrank) return "SPEED";
  if (hasCrank && !hasWheel) return "CADENCE";
  if (!hasWheel && !hasCrank) return null;
  if (wheelEventChanged && !crankEventChanged) return "SPEED";
  if (crankEventChanged && !wheelEventChanged) return "CADENCE";
  if (previousMode === "SPEED" || previousMode === "CADENCE") return previousMode;
  return "CADENCE";
}

export function parseCscMeasurement(value, previous = {}, wheelCircumferenceMm = DEFAULT_WHEEL_CIRCUMFERENCE_MM) {
  if (!(value instanceof DataView)) throw new TypeError("Pomiar CSC musi być obiektem DataView.");
  if (value.byteLength < 1) throw new RangeError("Pakiet CSC nie zawiera bajtu flag.");

  const circumferenceMm = Number(wheelCircumferenceMm);
  if (!Number.isFinite(circumferenceMm) || circumferenceMm <= 0) {
    throw new RangeError("Obwód koła musi być dodatnią liczbą milimetrów.");
  }

  const flags = value.getUint8(0);
  const hasWheel = (flags & 0x01) !== 0;
  const hasCrank = (flags & 0x02) !== 0;
  let offset = 1;
  let wheel = null;
  let crank = null;

  if (hasWheel) {
    if (value.byteLength < offset + 6) throw new RangeError("Niepełne dane obrotów koła w pakiecie CSC.");
    wheel = {
      revolutions: value.getUint32(offset, true),
      eventTime: value.getUint16(offset + 4, true),
    };
    offset += 6;
  }

  if (hasCrank) {
    if (value.byteLength < offset + 4) throw new RangeError("Niepełne dane obrotów korby w pakiecie CSC.");
    crank = {
      revolutions: value.getUint16(offset, true),
      eventTime: value.getUint16(offset + 2, true),
    };
  }

  const previousWheel = previous?.wheel || null;
  const previousCrank = previous?.crank || null;
  const wheelEventChanged = Boolean(wheel && (!previousWheel
    || wheel.revolutions !== previousWheel.revolutions
    || wheel.eventTime !== previousWheel.eventTime));
  const crankEventChanged = Boolean(crank && (!previousCrank
    || crank.revolutions !== previousCrank.revolutions
    || crank.eventTime !== previousCrank.eventTime));

  let speedKmh = null;
  if (wheel && previousWheel) {
    const revolutions = unsignedDelta(wheel.revolutions, previousWheel.revolutions, UINT32_MODULUS);
    const eventTicks = unsignedDelta(wheel.eventTime, previousWheel.eventTime, UINT16_MODULUS);
    if (eventTicks > 0) {
      const elapsedSeconds = eventTicks / CSC_EVENT_TICKS_PER_SECOND;
      speedKmh = finiteNonNegative((revolutions * circumferenceMm / 1_000_000) / elapsedSeconds * 3600);
    }
  }

  let rpm = null;
  if (crank && previousCrank) {
    const revolutions = unsignedDelta(crank.revolutions, previousCrank.revolutions, UINT16_MODULUS);
    const eventTicks = unsignedDelta(crank.eventTime, previousCrank.eventTime, UINT16_MODULUS);
    if (eventTicks > 0) {
      const elapsedSeconds = eventTicks / CSC_EVENT_TICKS_PER_SECOND;
      rpm = finiteNonNegative(revolutions / elapsedSeconds * 60);
    }
  }

  const mode = selectMode({
    hasWheel,
    hasCrank,
    wheelEventChanged,
    crankEventChanged,
    previousMode: previous?.mode,
  });

  return {
    flags,
    hasWheel,
    hasCrank,
    mode,
    speedKmh,
    rpm,
    wheel,
    crank,
    eventChanged: mode === "SPEED" ? wheelEventChanged : mode === "CADENCE" ? crankEventChanged : false,
    state: {
      wheel: wheel || previousWheel,
      crank: crank || previousCrank,
      mode,
    },
  };
}

export class CscBluetoothSensor {
  constructor({
    bluetooth = globalThis.navigator?.bluetooth,
    wheelCircumferenceMm = DEFAULT_WHEEL_CIRCUMFERENCE_MM,
    inactivityMs = CSC_INACTIVITY_MS,
    staleGraceMs = CSC_STALE_GRACE_MS,
    reconnectDelaysMs = CSC_RECONNECT_DELAYS_MS,
    connectionTimeoutMs = CSC_CONNECTION_TIMEOUT_MS,
    storage = globalThis.localStorage,
    lastDeviceStorageKey = CSC_LAST_DEVICE_STORAGE_KEY,
    onStateChange = () => {},
    onMeasurement = () => {},
    onError = () => {},
    onDiagnostic = () => {},
  } = {}) {
    this.bluetooth = bluetooth;
    this.wheelCircumferenceMm = Number(wheelCircumferenceMm);
    this.inactivityMs = inactivityMs;
    this.staleGraceMs = staleGraceMs;
    this.reconnectDelaysMs = reconnectDelaysMs.length ? [...reconnectDelaysMs] : [...CSC_RECONNECT_DELAYS_MS];
    this.connectionTimeoutMs = connectionTimeoutMs;
    this.storage = storage;
    this.lastDeviceStorageKey = lastDeviceStorageKey;
    this.onStateChange = onStateChange;
    this.onMeasurement = onMeasurement;
    this.onError = onError;
    this.onDiagnostic = onDiagnostic;
    this.diagnosticEntries = [];
    this.status = "disconnected";
    this.mode = null;
    this.rpm = null;
    this.speedKmh = null;
    this.device = null;
    this.characteristic = null;
    this.previousMeasurement = {};
    this.inactivityTimer = null;
    this.zeroTimer = null;
    this.reconnectTimer = null;
    this.reconnectAttempt = 0;
    this.retryDelayMs = 0;
    this.manualDisconnect = false;
    this.connectionGeneration = 0;
    this.pendingConnection = null;
    this.pendingReconnect = null;
    this.stale = false;
    this.handleMeasurement = this.handleMeasurement.bind(this);
    this.handleDisconnected = this.handleDisconnected.bind(this);
  }

  snapshot() {
    return {
      status: this.status,
      mode: this.mode,
      rpm: this.rpm,
      speedKmh: this.speedKmh,
      value: this.mode === "CADENCE" ? this.rpm : this.mode === "SPEED" ? this.speedKmh : null,
      deviceName: this.device?.name || null,
      wheelCircumferenceMm: this.wheelCircumferenceMm,
      stale: this.stale,
      reconnectAttempt: this.reconnectAttempt,
      retryDelayMs: this.retryDelayMs,
    };
  }

  emitState() {
    this.onStateChange(this.snapshot());
  }

  recordDiagnostic(message, error = null) {
    const entry = {
      at: Date.now(),
      message,
      error: error ? `${error.name || "Error"}: ${error.message || "brak szczegółów"}` : null,
    };
    this.diagnosticEntries.push(entry);
    if (this.diagnosticEntries.length > 30) this.diagnosticEntries.shift();
    this.onDiagnostic(this.diagnosticEntries.slice());
  }

  getDiagnostics() {
    return this.diagnosticEntries.slice();
  }

  setWheelCircumferenceMm(value) {
    const circumferenceMm = Number(value);
    if (!Number.isFinite(circumferenceMm) || circumferenceMm <= 0) {
      throw new RangeError("Obwód koła musi być dodatnią liczbą milimetrów.");
    }
    this.wheelCircumferenceMm = circumferenceMm;
    this.emitState();
  }

  rememberDevice(device) {
    if (!device?.id) return;
    try {
      this.storage?.setItem(this.lastDeviceStorageKey, device.id);
    } catch {}
  }

  forgetDevice(device = this.device) {
    if (!device?.id || this.lastDeviceId() !== device.id) return;
    try {
      this.storage?.removeItem(this.lastDeviceStorageKey);
    } catch {}
  }

  lastDeviceId() {
    try {
      return this.storage?.getItem(this.lastDeviceStorageKey) || null;
    } catch {
      return null;
    }
  }

  disconnectGattSilently(device = this.device, force = false) {
    try {
      if (device?.gatt && (force || device.gatt.connected)) device.gatt.disconnect();
    } catch {}
  }

  async connectDevice(device, { remember = false, expectedGeneration = this.connectionGeneration } = {}) {
    if (!device?.gatt?.connect) {
      throw connectionError(
        "Wybrany czujnik nie udostępnia połączenia Bluetooth GATT.",
        "csc_gatt_missing",
      );
    }
    const ensureCurrentConnection = () => {
      if (expectedGeneration === this.connectionGeneration && this.device === device
        && !this.manualDisconnect && device.gatt.connected) return;
      try {
        if (device.gatt.connected) device.gatt.disconnect();
      } catch {}
      const error = new Error("Łączenie z czujnikiem CSC zostało anulowane.");
      error.name = "AbortError";
      throw error;
    };
    this.cancelReconnectTimer();
    this.device?.removeEventListener("gattserverdisconnected", this.handleDisconnected);
    this.device = device;
    device.addEventListener("gattserverdisconnected", this.handleDisconnected);
    this.characteristic?.removeEventListener("characteristicvaluechanged", this.handleMeasurement);
    this.characteristic = null;
    this.previousMeasurement = {};

    const server = await withTimeout(device.gatt.connect(), this.connectionTimeoutMs, "Połączenie Bluetooth");
    ensureCurrentConnection();
    let service;
    try {
      service = await withTimeout(server.getPrimaryService(CSC_SERVICE_UUID), this.connectionTimeoutMs, "Wyszukiwanie usługi CSC");
    } catch (error) {
      if (error?.name === "TimeoutError") throw error;
      if (["SecurityError", "NotSupportedError"].includes(error?.name)) throw error;
      const transient = transientGattError(error, device);
      if (transient) throw transient;
      throw connectionError("Wybrane urządzenie nie udostępnia usługi CSC.", "csc_service_missing", error);
    }
    ensureCurrentConnection();
    try {
      this.characteristic = await withTimeout(service.getCharacteristic(CSC_MEASUREMENT_UUID), this.connectionTimeoutMs, "Wyszukiwanie pomiaru CSC");
    } catch (error) {
      if (error?.name === "TimeoutError") throw error;
      if (["SecurityError", "NotSupportedError"].includes(error?.name)) throw error;
      const transient = transientGattError(error, device);
      if (transient) throw transient;
      throw connectionError("Czujnik nie udostępnia charakterystyki pomiarowej CSC.", "csc_characteristic_missing", error);
    }
    ensureCurrentConnection();
    this.characteristic.addEventListener("characteristicvaluechanged", this.handleMeasurement);
    await withTimeout(this.characteristic.startNotifications(), this.connectionTimeoutMs, "Uruchamianie pomiarów CSC");
    ensureCurrentConnection();
    this.status = "connected";
    this.stale = true;
    this.reconnectAttempt = 0;
    this.retryDelayMs = 0;
    if (remember) this.rememberDevice(device);
    this.recordDiagnostic(`Połączono z ${device.name || "czujnikiem CSC"}; czekam na świeży pomiar.`);
    this.emitState();
    return this.snapshot();
  }

  async connect() {
    if (this.status === "connected") return this.snapshot();
    if (this.pendingConnection) return this.pendingConnection;
    if (this.status !== "disconnected") return this.snapshot();
    if (!this.bluetooth?.requestDevice) {
      throw new Error("Web Bluetooth wymaga Chrome/Edge oraz HTTPS albo localhost. Na zwykłym adresie HTTP w sieci LAN przeglądarka może go zablokować.");
    }

    this.connectionGeneration += 1;
    const expectedGeneration = this.connectionGeneration;
    this.manualDisconnect = false;
    this.status = "connecting";
    this.recordDiagnostic("Otwieram wybór czujnika Bluetooth.");
    this.reconnectAttempt = 0;
    this.retryDelayMs = 0;
    this.emitState();
    const attempt = (async () => {
      let device = null;
      try {
        device = await this.bluetooth.requestDevice(cscDeviceRequestOptions());
        if (expectedGeneration !== this.connectionGeneration || this.manualDisconnect) {
          const error = new Error("Łączenie z czujnikiem CSC zostało anulowane.");
          error.name = "AbortError";
          throw error;
        }
        return await this.connectDevice(device, { remember: true, expectedGeneration });
      } catch (error) {
        if (expectedGeneration === this.connectionGeneration) {
          this.recordDiagnostic("Ręczne połączenie nie powiodło się.", error);
          this.disconnectGattSilently(device, error?.name === "TimeoutError");
          this.resetConnection();
        }
        throw error;
      }
    })();
    this.pendingConnection = attempt;
    try {
      return await attempt;
    } finally {
      if (this.pendingConnection === attempt) this.pendingConnection = null;
    }
  }

  async reconnectLast() {
    if (this.pendingReconnect) return this.pendingReconnect;
    const attempt = this.reconnectLastOnce();
    this.pendingReconnect = attempt;
    try {
      return await attempt;
    } finally {
      if (this.pendingReconnect === attempt) this.pendingReconnect = null;
    }
  }

  async reconnectLastOnce() {
    if (this.status !== "disconnected") return this.snapshot();
    if (!this.bluetooth?.getDevices) {
      this.recordDiagnostic("Przeglądarka nie udostępnia listy zapamiętanych urządzeń; użyj POŁĄCZ CSC.");
      return this.snapshot();
    }
    const lastDeviceId = this.lastDeviceId();
    if (!lastDeviceId) {
      this.recordDiagnostic("Nie ma zapamiętanego czujnika; pierwsze połączenie wymaga kliknięcia POŁĄCZ CSC.");
      return this.snapshot();
    }

    const expectedGeneration = this.connectionGeneration;
    let devices;
    try {
      devices = await this.bluetooth.getDevices();
    } catch (error) {
      this.recordDiagnostic("Nie udało się odczytać zapamiętanych urządzeń.", error);
      return this.snapshot();
    }
    if (this.status !== "disconnected" || expectedGeneration !== this.connectionGeneration) return this.snapshot();
    const device = devices.find((candidate) => candidate.id === lastDeviceId);
    if (!device) {
      this.recordDiagnostic("Przeglądarka nie zwróciła zapamiętanego czujnika; wybierz go ponownie.");
      return this.snapshot();
    }

    this.recordDiagnostic(`Próbuję połączyć zapamiętany czujnik ${device.name || "CSC"}.`);
    this.device = device;
    this.status = "reconnecting";
    this.stale = true;
    this.emitState();
    try {
      return await this.connectDevice(device, { expectedGeneration });
    } catch (error) {
      if (expectedGeneration !== this.connectionGeneration) return this.snapshot();
      this.recordDiagnostic("Połączenie zapamiętanego czujnika nie powiodło się.", error);
      if (isRetryableConnectionError(error)) {
        this.disconnectGattSilently(device, error?.name === "TimeoutError");
        this.beginReconnect();
      }
      else {
        this.forgetDevice(device);
        this.disconnectGattSilently(device);
        this.resetConnection();
      }
      return this.snapshot();
    }
  }

  async disconnect() {
    this.manualDisconnect = true;
    this.connectionGeneration += 1;
    this.pendingConnection = null;
    this.pendingReconnect = null;
    this.cancelReconnectTimer();
    const characteristic = this.characteristic;
    const device = this.device;
    characteristic?.removeEventListener("characteristicvaluechanged", this.handleMeasurement);
    device?.removeEventListener("gattserverdisconnected", this.handleDisconnected);
    try {
      const stopped = characteristic?.stopNotifications?.();
      stopped?.catch?.(() => {});
    } catch {}
    this.disconnectGattSilently(device, true);
    this.resetConnection();
    this.manualDisconnect = false;
    this.recordDiagnostic("Rozłączono ręcznie; automatyczne próby zatrzymane.");
  }

  isCurrentMeasurement(event) {
    return this.status === "connected" && event?.target === this.characteristic;
  }

  handleMeasurement(event) {
    if (!this.isCurrentMeasurement(event)) return;
    try {
      const parsed = parseCscMeasurement(
        event?.target?.value,
        this.previousMeasurement,
        this.wheelCircumferenceMm,
      );
      this.previousMeasurement = parsed.state;
      this.mode = parsed.mode;
      if (parsed.rpm != null) this.rpm = parsed.rpm;
      if (parsed.speedKmh != null) this.speedKmh = parsed.speedKmh;
      if (parsed.eventChanged) {
        if (parsed.mode === "CADENCE" && parsed.rpm != null
          || parsed.mode === "SPEED" && parsed.speedKmh != null) this.stale = false;
        this.armInactivityTimer();
      }
      const snapshot = this.snapshot();
      this.onMeasurement({ ...snapshot, parsed, inactive: false, zeroed: false });
      this.emitState();
    } catch (error) {
      this.onError(error);
    }
  }

  armInactivityTimer() {
    clearTimeout(this.inactivityTimer);
    clearTimeout(this.zeroTimer);
    this.zeroTimer = null;
    this.inactivityTimer = setTimeout(() => {
      if (this.status !== "connected") return;
      this.stale = true;
      const snapshot = this.snapshot();
      this.onMeasurement({ ...snapshot, parsed: null, inactive: true, zeroed: false });
      this.emitState();
      this.zeroTimer = setTimeout(() => {
        if (this.status !== "connected") return;
        if (this.device?.gatt?.connected === false) {
          this.checkConnection();
          return;
        }
        if (this.mode === "CADENCE") this.rpm = 0;
        if (this.mode === "SPEED") this.speedKmh = 0;
        // No measurement arrived: the displayed zero must not masquerade as a fresh reading.
        this.stale = true;
        const zeroSnapshot = this.snapshot();
        this.onMeasurement({ ...zeroSnapshot, parsed: null, inactive: true, zeroed: true });
        this.emitState();
      }, this.staleGraceMs);
    }, this.inactivityMs);
  }

  handleDisconnected(event) {
    if (event?.target && event.target !== this.device) return;
    if (this.manualDisconnect) return;
    if (this.status === "connecting" || this.status === "disconnected") return;
    this.recordDiagnostic("Utracono połączenie Bluetooth.");
    this.beginReconnect();
  }

  checkConnection() {
    if (this.status === "connected" && this.device?.gatt?.connected === false) {
      this.recordDiagnostic("Połączenie GATT zniknęło bez zdarzenia rozłączenia.");
      this.beginReconnect();
    }
    return this.snapshot();
  }

  beginReconnect() {
    this.connectionGeneration += 1;
    clearTimeout(this.inactivityTimer);
    clearTimeout(this.zeroTimer);
    this.inactivityTimer = null;
    this.zeroTimer = null;
    this.characteristic?.removeEventListener("characteristicvaluechanged", this.handleMeasurement);
    this.characteristic = null;
    if (!this.device) {
      this.resetConnection();
      return;
    }
    this.status = "reconnecting";
    this.stale = true;
    this.scheduleReconnect();
  }

  scheduleReconnect() {
    if (this.manualDisconnect || this.status !== "reconnecting" || this.reconnectTimer) return;
    const delayIndex = Math.min(this.reconnectAttempt, this.reconnectDelaysMs.length - 1);
    this.retryDelayMs = this.reconnectDelaysMs[delayIndex];
    this.reconnectAttempt += 1;
    this.recordDiagnostic(`Ponowna próba ${this.reconnectAttempt} za ${Math.ceil(this.retryDelayMs / 1000)} s.`);
    this.emitState();
    this.reconnectTimer = setTimeout(async () => {
      this.reconnectTimer = null;
      if (this.manualDisconnect || this.status !== "reconnecting" || !this.device) return;
      const expectedGeneration = this.connectionGeneration;
      this.retryDelayMs = 0;
      this.recordDiagnostic(`Rozpoczęto próbę ${this.reconnectAttempt}.`);
      this.emitState();
      try {
        await this.connectDevice(this.device, { expectedGeneration });
      } catch (error) {
        if (expectedGeneration !== this.connectionGeneration) return;
        this.recordDiagnostic(`Próba ${this.reconnectAttempt} nie powiodła się.`, error);
        this.disconnectGattSilently(this.device, error?.name === "TimeoutError");
        if (isRetryableConnectionError(error)) {
          this.status = "reconnecting";
          this.scheduleReconnect();
        } else {
          this.forgetDevice();
          this.disconnectGattSilently();
          this.resetConnection();
          this.onError(error);
        }
      }
    }, this.retryDelayMs);
  }

  cancelReconnectTimer() {
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.retryDelayMs = 0;
  }

  resetConnection() {
    clearTimeout(this.inactivityTimer);
    clearTimeout(this.zeroTimer);
    this.inactivityTimer = null;
    this.zeroTimer = null;
    this.cancelReconnectTimer();
    this.characteristic?.removeEventListener("characteristicvaluechanged", this.handleMeasurement);
    this.device?.removeEventListener("gattserverdisconnected", this.handleDisconnected);
    this.status = "disconnected";
    this.mode = null;
    this.rpm = null;
    this.speedKmh = null;
    this.stale = false;
    this.reconnectAttempt = 0;
    this.characteristic = null;
    this.device = null;
    this.previousMeasurement = {};
    this.emitState();
  }
}
