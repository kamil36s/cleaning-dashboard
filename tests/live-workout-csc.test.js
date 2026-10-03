import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CSC_MEASUREMENT_UUID,
  CSC_SERVICE_UUID,
  CscBluetoothSensor,
  cscDeviceRequestOptions,
  formatCscConnectionError,
  parseCscMeasurement,
} from "../js/live-workout-csc.js";
import { deriveCyclingSpeedKmh } from "../js/live-workout-distance.js";

function cadenceMeasurement(revolutions, eventTime) {
  const value = new DataView(new ArrayBuffer(5));
  value.setUint8(0, 0x02);
  value.setUint16(1, revolutions, true);
  value.setUint16(3, eventTime, true);
  return value;
}

function speedMeasurement(revolutions, eventTime) {
  const value = new DataView(new ArrayBuffer(7));
  value.setUint8(0, 0x01);
  value.setUint32(1, revolutions, true);
  value.setUint16(5, eventTime, true);
  return value;
}

function combinedMeasurement({ wheelRevolutions, wheelTime, crankRevolutions, crankTime }) {
  const value = new DataView(new ArrayBuffer(11));
  value.setUint8(0, 0x03);
  value.setUint32(1, wheelRevolutions, true);
  value.setUint16(5, wheelTime, true);
  value.setUint16(7, crankRevolutions, true);
  value.setUint16(9, crankTime, true);
  return value;
}

function mockCscDevice(id = "magene-test") {
  const deviceListeners = new Map();
  const measurementListeners = new Map();
  const characteristic = {
    value: null,
    addEventListener: vi.fn((type, listener) => measurementListeners.set(type, listener)),
    removeEventListener: vi.fn((type) => measurementListeners.delete(type)),
    startNotifications: vi.fn(async () => characteristic),
    stopNotifications: vi.fn(async () => characteristic),
  };
  const service = { getCharacteristic: vi.fn(async () => characteristic) };
  const server = { getPrimaryService: vi.fn(async () => service) };
  const device = {
    id,
    name: "Magene Test",
    addEventListener: vi.fn((type, listener) => deviceListeners.set(type, listener)),
    removeEventListener: vi.fn((type) => deviceListeners.delete(type)),
    gatt: {
      connected: false,
      connect: vi.fn(async () => {
        device.gatt.connected = true;
        return server;
      }),
      disconnect: vi.fn(() => { device.gatt.connected = false; }),
    },
  };
  const send = (value) => {
    characteristic.value = value;
    measurementListeners.get("characteristicvaluechanged")?.({ target: characteristic });
  };
  const drop = () => {
    device.gatt.connected = false;
    deviceListeners.get("gattserverdisconnected")?.({ target: device });
  };
  return { device, server, service, characteristic, send, drop, deviceListeners, measurementListeners };
}

describe("Bluetooth CSC parser", () => {
  it("calculates cadence and handles the uint16 event timer wrap", () => {
    const first = parseCscMeasurement(cadenceMeasurement(100, 65_000));
    const second = parseCscMeasurement(cadenceMeasurement(101, 232), first.state);

    expect(second.mode).toBe("CADENCE");
    expect(second.rpm).toBeCloseTo(80, 4);
  });

  it("calculates wheel speed using the configured circumference", () => {
    const first = parseCscMeasurement(speedMeasurement(500, 1000));
    const second = parseCscMeasurement(speedMeasurement(501, 2024), first.state, 2096);

    expect(second.mode).toBe("SPEED");
    expect(second.speedKmh).toBeCloseTo(7.5456, 4);
  });

  it("parses both fields at their CSC offsets and follows the field with a new event", () => {
    const first = parseCscMeasurement(combinedMeasurement({
      wheelRevolutions: 20,
      wheelTime: 1000,
      crankRevolutions: 10,
      crankTime: 1000,
    }));
    const second = parseCscMeasurement(combinedMeasurement({
      wheelRevolutions: 21,
      wheelTime: 2024,
      crankRevolutions: 10,
      crankTime: 1000,
    }), first.state);

    expect(first.mode).toBe("CADENCE");
    expect(second.mode).toBe("SPEED");
    expect(second.wheel.revolutions).toBe(21);
    expect(second.crank.revolutions).toBe(10);
  });

  it("does not divide by zero for a repeated event time", () => {
    const first = parseCscMeasurement(cadenceMeasurement(10, 1000));
    const second = parseCscMeasurement(cadenceMeasurement(11, 1000), first.state);

    expect(second.rpm).toBeNull();
  });
});

describe("Bluetooth CSC connection", () => {
  afterEach(() => vi.useRealTimers());

  it("holds a briefly stale RPM, restores it on fresh data, then zeroes a longer loss", async () => {
    vi.useFakeTimers();
    const listeners = new Map();
    const characteristic = {
      value: null,
      addEventListener: vi.fn((type, listener) => listeners.set(type, listener)),
      removeEventListener: vi.fn((type) => listeners.delete(type)),
      startNotifications: vi.fn(async () => characteristic),
      stopNotifications: vi.fn(async () => characteristic),
    };
    const service = { getCharacteristic: vi.fn(async () => characteristic) };
    const server = { getPrimaryService: vi.fn(async () => service) };
    const deviceListeners = new Map();
    const device = {
      name: "Bike CSC",
      addEventListener: vi.fn((type, listener) => deviceListeners.set(type, listener)),
      removeEventListener: vi.fn((type) => deviceListeners.delete(type)),
      gatt: {
        connected: false,
        connect: vi.fn(async () => {
          device.gatt.connected = true;
          return server;
        }),
        disconnect: vi.fn(() => { device.gatt.connected = false; }),
      },
    };
    const bluetooth = { requestDevice: vi.fn(async () => device) };
    const measurements = [];
    const sensor = new CscBluetoothSensor({
      bluetooth,
      inactivityMs: 2000,
      staleGraceMs: 2000,
      onMeasurement: (measurement) => measurements.push(measurement),
    });

    await sensor.connect();
    expect(bluetooth.requestDevice).toHaveBeenCalledWith({
      acceptAllDevices: true,
      optionalServices: [CSC_SERVICE_UUID],
    });
    expect(server.getPrimaryService).toHaveBeenCalledWith(CSC_SERVICE_UUID);
    expect(service.getCharacteristic).toHaveBeenCalledWith(CSC_MEASUREMENT_UUID);
    expect(characteristic.startNotifications).toHaveBeenCalledOnce();

    const notify = listeners.get("characteristicvaluechanged");
    const send = (value) => {
      characteristic.value = value;
      notify({ target: characteristic });
    };
    send(cadenceMeasurement(10, 1000));
    send(cadenceMeasurement(11, 1768));
    expect(sensor.snapshot()).toMatchObject({ status: "connected", mode: "CADENCE" });
    expect(sensor.snapshot().rpm).toBeCloseTo(80, 4);

    await vi.advanceTimersByTimeAsync(2001);
    expect(sensor.snapshot()).toMatchObject({ stale: true });
    expect(sensor.snapshot().rpm).toBeCloseTo(80, 4);
    expect(measurements.at(-1)).toMatchObject({ inactive: true, stale: true, zeroed: false });

    send(cadenceMeasurement(12, 2536));
    expect(sensor.snapshot()).toMatchObject({ stale: false });
    expect(sensor.snapshot().rpm).toBeCloseTo(80, 4);

    await vi.advanceTimersByTimeAsync(2001);
    expect(sensor.snapshot()).toMatchObject({ stale: true });
    await vi.advanceTimersByTimeAsync(2001);
    expect(sensor.snapshot()).toMatchObject({ rpm: 0, stale: true });
    expect(measurements.at(-1)).toMatchObject({ inactive: true, value: 0, zeroed: true });
    const stale = sensor.snapshot();
    expect(deriveCyclingSpeedKmh({
      cadenceRpm: stale.stale ? null : stale.rpm,
      heartRate: 135,
      maxHeartRate: 180,
    })).toMatchObject({ source: "heart_rate_virtual_distance_v1" });

    await sensor.disconnect();
    expect(characteristic.stopNotifications).toHaveBeenCalledOnce();
    expect(device.gatt.disconnect).toHaveBeenCalledOnce();
    expect(sensor.snapshot()).toMatchObject({ status: "disconnected", mode: null, value: null });
  });

  it("reconnects to the last granted sensor without opening the device picker", async () => {
    vi.useFakeTimers();
    const characteristic = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      startNotifications: vi.fn(async () => characteristic),
      stopNotifications: vi.fn(async () => characteristic),
    };
    const service = { getCharacteristic: vi.fn(async () => characteristic) };
    const server = { getPrimaryService: vi.fn(async () => service) };
    const device = {
      id: "magene-c406",
      name: "Magene C406",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      gatt: {
        connected: false,
        connect: vi.fn()
          .mockRejectedValueOnce(new Error("radio unavailable"))
          .mockImplementation(async () => {
            device.gatt.connected = true;
            return server;
          }),
        disconnect: vi.fn(),
      },
    };
    const storage = {
      getItem: vi.fn(() => "magene-c406"),
      setItem: vi.fn(),
    };
    const bluetooth = {
      getDevices: vi.fn(async () => [device]),
      requestDevice: vi.fn(),
    };
    const sensor = new CscBluetoothSensor({
      bluetooth,
      storage,
      reconnectDelaysMs: [1000],
    });

    await sensor.reconnectLast();
    expect(bluetooth.getDevices).toHaveBeenCalledOnce();
    expect(bluetooth.requestDevice).not.toHaveBeenCalled();
    expect(sensor.snapshot()).toMatchObject({
      status: "reconnecting",
      deviceName: "Magene C406",
      reconnectAttempt: 1,
      retryDelayMs: 1000,
    });

    await vi.advanceTimersByTimeAsync(1000);
    expect(device.gatt.connect).toHaveBeenCalledTimes(2);
    expect(sensor.snapshot()).toMatchObject({ status: "connected", deviceName: "Magene C406" });
  });

  it("keeps the last cadence during a brief disconnect and cancels retry on manual disconnect", async () => {
    vi.useFakeTimers();
    const characteristicListeners = new Map();
    const characteristic = {
      value: null,
      addEventListener: vi.fn((type, listener) => characteristicListeners.set(type, listener)),
      removeEventListener: vi.fn((type) => characteristicListeners.delete(type)),
      startNotifications: vi.fn(async () => characteristic),
      stopNotifications: vi.fn(async () => characteristic),
    };
    const service = { getCharacteristic: vi.fn(async () => characteristic) };
    const server = { getPrimaryService: vi.fn(async () => service) };
    const deviceListeners = new Map();
    const device = {
      id: "magene-csc",
      name: "Magene CSC",
      addEventListener: vi.fn((type, listener) => deviceListeners.set(type, listener)),
      removeEventListener: vi.fn((type) => deviceListeners.delete(type)),
      gatt: {
        connected: false,
        connect: vi.fn(async () => {
          device.gatt.connected = true;
          return server;
        }),
        disconnect: vi.fn(() => { device.gatt.connected = false; }),
      },
    };
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => device) },
      storage: { getItem: vi.fn(), setItem: vi.fn() },
      reconnectDelaysMs: [1000],
    });

    await sensor.connect();
    const notify = characteristicListeners.get("characteristicvaluechanged");
    characteristic.value = cadenceMeasurement(10, 1000);
    notify({ target: characteristic });
    characteristic.value = cadenceMeasurement(11, 1768);
    notify({ target: characteristic });
    expect(sensor.snapshot().rpm).toBeCloseTo(80, 4);

    device.gatt.connected = false;
    deviceListeners.get("gattserverdisconnected")({ target: device });
    expect(sensor.snapshot()).toMatchObject({ status: "reconnecting", stale: true });
    expect(sensor.snapshot().rpm).toBeCloseTo(80, 4);

    await sensor.disconnect();
    await vi.advanceTimersByTimeAsync(1000);
    expect(device.gatt.connect).toHaveBeenCalledOnce();
    expect(sensor.snapshot()).toMatchObject({ status: "disconnected", value: null });
  });

  it("shows Magene devices that do not advertise CSC before connecting", () => {
    expect(cscDeviceRequestOptions()).toEqual({
      acceptAllDevices: true,
      optionalServices: [CSC_SERVICE_UUID],
    });
  });

  it("returns to disconnected after picker cancellation and allows another attempt", async () => {
    const cancelled = new Error("User cancelled");
    cancelled.name = "NotFoundError";
    const bluetooth = {
      requestDevice: vi.fn()
        .mockRejectedValueOnce(cancelled)
        .mockRejectedValueOnce(cancelled),
    };
    const sensor = new CscBluetoothSensor({ bluetooth });

    await expect(sensor.connect()).rejects.toBe(cancelled);
    expect(sensor.snapshot()).toMatchObject({ status: "disconnected", reconnectAttempt: 0 });
    await expect(sensor.connect()).rejects.toBe(cancelled);
    expect(bluetooth.requestDevice).toHaveBeenCalledTimes(2);
    expect(formatCscConnectionError(cancelled)).toContain("Zakręć korbą lub kołem");
  });

  it("can cancel a connection while the native device picker is pending", async () => {
    let resolvePicker;
    const picker = new Promise((resolve) => { resolvePicker = resolve; });
    const device = {
      id: "magene-pending",
      name: "Magene pending",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      gatt: {
        connected: false,
        connect: vi.fn(),
        disconnect: vi.fn(),
      },
    };
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(() => picker) },
    });

    const connection = sensor.connect();
    expect(sensor.snapshot().status).toBe("connecting");
    await sensor.disconnect();
    resolvePicker(device);

    await expect(connection).rejects.toMatchObject({ name: "AbortError" });
    expect(device.gatt.connect).not.toHaveBeenCalled();
    expect(sensor.snapshot().status).toBe("disconnected");
  });

  it("does not remember or retry a device when the first CSC handshake fails", async () => {
    vi.useFakeTimers();
    const missingService = new Error("Service not found");
    missingService.name = "NotFoundError";
    const server = { getPrimaryService: vi.fn(async () => { throw missingService; }) };
    const device = {
      id: "wrong-device",
      name: "Not a CSC sensor",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      gatt: {
        connected: false,
        connect: vi.fn(async () => {
          device.gatt.connected = true;
          return server;
        }),
        disconnect: vi.fn(() => { device.gatt.connected = false; }),
      },
    };
    const storage = { getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() };
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => device) },
      storage,
      reconnectDelaysMs: [10],
    });

    await expect(sensor.connect()).rejects.toMatchObject({ code: "csc_service_missing" });
    expect(storage.setItem).not.toHaveBeenCalled();
    expect(sensor.snapshot()).toMatchObject({ status: "disconnected", reconnectAttempt: 0 });
    await vi.advanceTimersByTimeAsync(100);
    expect(device.gatt.connect).toHaveBeenCalledOnce();
  });

  it("forgets a remembered non-CSC device instead of retrying forever", async () => {
    vi.useFakeTimers();
    const device = {
      id: "remembered-wrong-device",
      name: "Wrong remembered device",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      gatt: {
        connected: true,
        connect: vi.fn(async () => ({
          getPrimaryService: vi.fn(async () => { throw new Error("missing"); }),
        })),
        disconnect: vi.fn(() => { device.gatt.connected = false; }),
      },
    };
    const storage = {
      getItem: vi.fn(() => device.id),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    };
    const sensor = new CscBluetoothSensor({
      bluetooth: { getDevices: vi.fn(async () => [device]) },
      storage,
      reconnectDelaysMs: [10],
    });

    await sensor.reconnectLast();
    expect(storage.removeItem).toHaveBeenCalledWith("liveWorkout.csc.lastDeviceId");
    expect(device.gatt.disconnect).toHaveBeenCalledOnce();
    expect(sensor.snapshot().status).toBe("disconnected");
    await vi.advanceTimersByTimeAsync(100);
    expect(device.gatt.connect).toHaveBeenCalledOnce();
  });

  it("retries a transient service discovery failure after a lost connection", async () => {
    vi.useFakeTimers();
    const mock = mockCscDevice();
    const networkError = new Error("GATT Server is disconnected. Cannot retrieve services.");
    networkError.name = "NetworkError";
    mock.server.getPrimaryService
      .mockImplementationOnce(async () => mock.service)
      .mockRejectedValueOnce(networkError);
    const storage = { getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() };
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => mock.device) },
      storage,
      reconnectDelaysMs: [100, 200],
    });

    await sensor.connect();
    mock.drop();
    await vi.advanceTimersByTimeAsync(100);
    expect(sensor.snapshot()).toMatchObject({ status: "reconnecting", reconnectAttempt: 2 });
    expect(storage.removeItem).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(200);
    expect(sensor.snapshot()).toMatchObject({ status: "connected", stale: true });
    expect(mock.device.gatt.connect).toHaveBeenCalledTimes(3);
  });

  it("treats NotFoundError from a disconnected GATT service as temporary", async () => {
    vi.useFakeTimers();
    const mock = mockCscDevice();
    const missing = new Error("No Services found");
    missing.name = "NotFoundError";
    mock.server.getPrimaryService
      .mockImplementationOnce(async () => mock.service)
      .mockImplementationOnce(async () => {
        mock.device.gatt.connected = false;
        throw missing;
      });
    const storage = { getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() };
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => mock.device) },
      storage,
      reconnectDelaysMs: [100],
    });

    await sensor.connect();
    mock.drop();
    await vi.advanceTimersByTimeAsync(100);
    expect(sensor.snapshot().status).toBe("reconnecting");
    expect(storage.removeItem).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(100);
    expect(sensor.snapshot().status).toBe("connected");
  });

  it("keeps retrying when notification setup times out", async () => {
    vi.useFakeTimers();
    const mock = mockCscDevice();
    mock.characteristic.startNotifications
      .mockImplementationOnce(async () => mock.characteristic)
      .mockImplementationOnce(() => new Promise(() => {}));
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => mock.device) },
      reconnectDelaysMs: [100],
      connectionTimeoutMs: 50,
    });

    await sensor.connect();
    mock.drop();
    await vi.advanceTimersByTimeAsync(100);
    expect(sensor.snapshot()).toMatchObject({ status: "reconnecting", retryDelayMs: 0 });
    await vi.advanceTimersByTimeAsync(50);
    expect(sensor.snapshot()).toMatchObject({ status: "reconnecting", reconnectAttempt: 2 });
    await vi.advanceTimersByTimeAsync(100);
    expect(sensor.snapshot().status).toBe("connected");
    expect(mock.characteristic.startNotifications).toHaveBeenCalledTimes(3);
  });

  it("does not resume a timed-out handshake after manual disconnect", async () => {
    vi.useFakeTimers();
    const mock = mockCscDevice();
    mock.characteristic.startNotifications
      .mockImplementationOnce(async () => mock.characteristic)
      .mockImplementationOnce(() => new Promise(() => {}));
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => mock.device) },
      reconnectDelaysMs: [100],
      connectionTimeoutMs: 50,
    });

    await sensor.connect();
    mock.drop();
    await vi.advanceTimersByTimeAsync(100);
    await sensor.disconnect();
    await vi.advanceTimersByTimeAsync(500);
    expect(sensor.snapshot().status).toBe("disconnected");
    expect(mock.device.gatt.connect).toHaveBeenCalledTimes(2);
  });

  it("ignores an old service lookup after another disconnect and resumes on the next retry", async () => {
    vi.useFakeTimers();
    const mock = mockCscDevice();
    let resolveOldLookup;
    const oldLookup = new Promise((resolve) => { resolveOldLookup = resolve; });
    mock.server.getPrimaryService
      .mockImplementationOnce(async () => mock.service)
      .mockImplementationOnce(() => oldLookup);
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => mock.device) },
      reconnectDelaysMs: [100],
    });

    await sensor.connect();
    mock.drop();
    await vi.advanceTimersByTimeAsync(100);
    expect(mock.server.getPrimaryService).toHaveBeenCalledTimes(2);
    mock.drop();
    resolveOldLookup(mock.service);
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(100);
    expect(sensor.snapshot()).toMatchObject({ status: "connected", stale: true });
    expect(mock.device.gatt.connect).toHaveBeenCalledTimes(3);
  });

  it("does not let startup device discovery replace a manual connection", async () => {
    const remembered = mockCscDevice("remembered");
    const chosen = mockCscDevice("chosen");
    let resolveDevices;
    const devices = new Promise((resolve) => { resolveDevices = resolve; });
    const bluetooth = {
      getDevices: vi.fn(() => devices),
      requestDevice: vi.fn(async () => chosen.device),
    };
    const sensor = new CscBluetoothSensor({
      bluetooth,
      storage: { getItem: vi.fn(() => remembered.device.id), setItem: vi.fn() },
    });

    const startup = sensor.reconnectLast();
    await sensor.connect();
    resolveDevices([remembered.device]);
    await startup;
    expect(sensor.snapshot()).toMatchObject({ status: "connected", deviceName: "Magene Test" });
    expect(chosen.device.gatt.connect).toHaveBeenCalledOnce();
    expect(remembered.device.gatt.connect).not.toHaveBeenCalled();
  });

  it("coalesces simultaneous startup reconnect requests", async () => {
    const mock = mockCscDevice();
    const bluetooth = { getDevices: vi.fn(async () => [mock.device]) };
    const sensor = new CscBluetoothSensor({
      bluetooth,
      storage: { getItem: vi.fn(() => mock.device.id) },
    });

    await Promise.all([sensor.reconnectLast(), sensor.reconnectLast()]);
    expect(bluetooth.getDevices).toHaveBeenCalledOnce();
    expect(mock.device.gatt.connect).toHaveBeenCalledOnce();
  });

  it("recovers when GATT is gone but no disconnect event was delivered", async () => {
    vi.useFakeTimers();
    const mock = mockCscDevice();
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => mock.device) },
      reconnectDelaysMs: [100],
    });

    await sensor.connect();
    mock.device.gatt.connected = false;
    sensor.checkConnection();
    expect(sensor.snapshot()).toMatchObject({ status: "reconnecting", reconnectAttempt: 1 });
    await vi.advanceTimersByTimeAsync(100);
    expect(sensor.snapshot().status).toBe("connected");
  });

  it("explains when automatic reconnect is unavailable without forgetting the manual option", async () => {
    const diagnostics = vi.fn();
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn() },
      onDiagnostic: diagnostics,
    });

    await sensor.reconnectLast();
    expect(sensor.snapshot().status).toBe("disconnected");
    expect(sensor.getDiagnostics().at(-1).message).toContain("POŁĄCZ CSC");
    expect(diagnostics).toHaveBeenCalled();
  });

  it("keeps the recovered value stale until a second valid CSC measurement arrives", async () => {
    vi.useFakeTimers();
    const mock = mockCscDevice();
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => mock.device) },
      reconnectDelaysMs: [100],
    });

    await sensor.connect();
    mock.send(cadenceMeasurement(10, 1000));
    expect(sensor.snapshot()).toMatchObject({ stale: true, rpm: null });
    mock.send(cadenceMeasurement(11, 1768));
    expect(sensor.snapshot()).toMatchObject({ stale: false, rpm: 80 });
    mock.drop();
    await vi.advanceTimersByTimeAsync(100);
    mock.send(cadenceMeasurement(100, 3000));
    expect(sensor.snapshot()).toMatchObject({ status: "connected", stale: true, rpm: 80 });
    mock.send(cadenceMeasurement(101, 3768));
    expect(sensor.snapshot()).toMatchObject({ status: "connected", stale: false, rpm: 80 });
  });

  it("disconnects immediately even when stopping notifications never resolves", async () => {
    const mock = mockCscDevice();
    mock.characteristic.stopNotifications.mockImplementation(() => new Promise(() => {}));
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => mock.device) },
    });

    await sensor.connect();
    await sensor.disconnect();
    expect(sensor.snapshot().status).toBe("disconnected");
    expect(mock.device.gatt.disconnect).toHaveBeenCalledOnce();
  });

  it("keeps a bounded diagnostic history with the cause of failed retries", async () => {
    vi.useFakeTimers();
    const mock = mockCscDevice();
    const diagnostics = vi.fn();
    mock.device.gatt.connect
      .mockImplementationOnce(async () => {
        mock.device.gatt.connected = true;
        return mock.server;
      })
      .mockRejectedValue(new Error("radio busy"));
    const sensor = new CscBluetoothSensor({
      bluetooth: { requestDevice: vi.fn(async () => mock.device) },
      reconnectDelaysMs: [10],
      onDiagnostic: diagnostics,
    });

    await sensor.connect();
    mock.drop();
    await vi.advanceTimersByTimeAsync(100);
    expect(sensor.getDiagnostics().length).toBeLessThanOrEqual(30);
    expect(sensor.getDiagnostics().some((entry) => entry.error?.includes("radio busy"))).toBe(true);
    expect(diagnostics).toHaveBeenCalled();
    await sensor.disconnect();
  });
});
