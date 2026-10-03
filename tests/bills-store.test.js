import { beforeEach, describe, expect, it } from "vitest";

import {
  BILL_SCHEDULE,
  addCustomBill,
  cancelSubscription,
  getAverageMonthlyPlannedCents,
  getAverageMonthlyRemainingCents,
  getBillStatus,
  getMonthlyBillSummaries,
  getNextUnpaidManualBill,
  getTotalOutstandingCents,
  listBills,
  removeCustomBill,
  setBillPaid,
} from "../js/bills-store.js";

describe("recurring bills schedule", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("contains the apartment bills only through April 2027 and all 12 Santander installments", () => {
    const apartmentBills = BILL_SCHEDULE.filter((bill) => bill.category === "Mieszkanie");
    const santanderBills = BILL_SCHEDULE.filter((bill) => bill.id.startsWith("santander-piano"));

    expect(apartmentBills.every((bill) => bill.month <= "2027-04")).toBe(true);
    expect(apartmentBills.some((bill) => bill.month === "2027-05")).toBe(false);
    expect(santanderBills).toHaveLength(12);
    expect(santanderBills[0].due).toBe("2026-09-11");
    expect(santanderBills[0].note).toBe("Rata 4 z 15");
    expect(santanderBills.at(-1).due).toBe("2027-08-11");
    expect(santanderBills.at(-1).note).toBe("Rata 15 z 15");
  });

  it("starts the rent reminder on the penultimate day of the previous month", () => {
    const rent = { ...BILL_SCHEDULE.find((bill) => bill.id === "rent-2026-09"), paid: false };

    expect(rent.reminderFrom).toBe("2026-08-30");
    expect(getBillStatus(rent, new Date(2026, 7, 29)).key).toBe("upcoming");
    expect(getBillStatus(rent, new Date(2026, 7, 30)).key).toBe("attention");
    expect(getBillStatus(rent, new Date(2026, 8, 1)).key).toBe("critical");
    expect(getBillStatus(rent, new Date(2026, 8, 6)).key).toBe("overdue");
  });

  it("marks the unpaid August Play invoice as critical two days before payment", () => {
    const play = { ...BILL_SCHEDULE.find((bill) => bill.id === "play-internet-2026-08"), paid: false };
    const status = getBillStatus(play, new Date(2026, 7, 20));

    expect(status.key).toBe("critical");
    expect(status.daysLabel).toBe("zostało 2 dni");
  });

  it("calculates the planned and outstanding total for every month", () => {
    const summaries = getMonthlyBillSummaries(listBills(new Date(2026, 7, 20)));
    const august = summaries.find((summary) => summary.month === "2026-08");
    const october = summaries.find((summary) => summary.month === "2026-10");
    const may = summaries.find((summary) => summary.month === "2027-05");

    expect(august).toMatchObject({
      plannedCents: 303020,
      remainingCents: 45195,
      categoryTotals: { Mieszkanie: 265524, Raty: 0, Subskrypcje: 37496 },
    });
    expect(october).toMatchObject({ plannedCents: 374226, remainingCents: 374226 });
    expect(may).toMatchObject({ plannedCents: 54215, remainingCents: 54215 });
  });

  it("creates all automatic subscriptions monthly and clamps Canal+ in February", () => {
    const bills = listBills(new Date(2026, 7, 20));
    const augustSubscriptions = bills.filter((bill) => (
      bill.month === "2026-08" && bill.category === "Subskrypcje"
    ));
    const chatgpt = augustSubscriptions.find((bill) => bill.subscriptionId === "chatgpt");
    const canal = augustSubscriptions.find((bill) => bill.subscriptionId === "canal-plus");
    const februaryCanal = bills.find((bill) => bill.id === "subscription-canal-plus-2027-02");
    const septemberGlovo = bills.find((bill) => bill.id === "subscription-glovo-prime-2026-09");

    expect(augustSubscriptions).toHaveLength(6);
    expect(chatgpt).toMatchObject({ amountCents: 10000, due: "2026-08-17", paid: false });
    expect(canal).toMatchObject({ amountCents: 7900, due: "2026-08-29", paid: false });
    expect(getBillStatus(canal, new Date(2026, 7, 20)).key).toBe("automatic");
    expect(februaryCanal.due).toBe("2027-02-28");
    expect(septemberGlovo).toMatchObject({ amountCents: 1999, due: "2026-09-02", paid: false });
  });

  it("records the September ChatGPT Pro upgrade and returns to 100 zl afterward", () => {
    const bills = listBills(new Date(2026, 8, 16));
    const september = bills.find((bill) => bill.id === "subscription-chatgpt-2026-09");
    const october = bills.find((bill) => bill.id === "subscription-chatgpt-2026-10");

    expect(september).toMatchObject({ amountCents: 48844, due: "2026-09-16", paid: false });
    expect(october).toMatchObject({ amountCents: 10000, due: "2026-10-17", paid: false });
  });

  it("removes a cancelled subscription from the whole widget schedule", () => {
    expect(cancelSubscription("spotify")).toBe(true);

    const bills = listBills(new Date(2026, 7, 20));
    expect(bills.some((bill) => bill.subscriptionId === "spotify")).toBe(false);
    expect(JSON.parse(localStorage.getItem("todo-bills-v1")).cancelledSubscriptions).toEqual({
      spotify: true,
    });
  });

  it("persists an independently paid occurrence without changing the rest of the series", () => {
    setBillPaid("play-internet-2026-08", true);

    expect(listBills().find((bill) => bill.id === "play-internet-2026-08")?.paid).toBe(true);
    expect(listBills().find((bill) => bill.id === "play-internet-2026-09")?.paid).toBe(false);
    expect(JSON.parse(localStorage.getItem("todo-bills-v1")).paid).toMatchObject({
      "play-internet-2026-08": true,
    });
  });

  it("calculates the outstanding total through April and reduces it after a payment", () => {
    const totalOutstanding = () => getTotalOutstandingCents(listBills(new Date(2026, 7, 20)));
    const before = totalOutstanding();

    expect(before).toBe(2819844);

    setBillPaid("play-internet-2026-08", true);

    expect(before - totalOutstanding()).toBe(7699);
  });

  it("calculates the average monthly plan through April 2027", () => {
    const average = getAverageMonthlyPlannedCents(
      listBills(new Date(2026, 7, 21)),
      "2026-08",
      "2027-04",
    );

    expect(average).toBe(341963);
  });

  it("calculates the real average from the next month and reflects advance payments", () => {
    const now = new Date(2026, 7, 21);
    const average = () => getAverageMonthlyRemainingCents(
      listBills(now),
      "2026-09",
      "2027-04",
    );

    expect(average()).toBe(346831);
    setBillPaid("rent-2026-09", true);
    expect(average()).toBe(314603);
  });

  it("finds the next unpaid non-automatic payment", () => {
    setBillPaid("play-internet-2026-08", true);

    const next = getNextUnpaidManualBill(
      listBills(new Date(2026, 7, 21)),
      new Date(2026, 7, 21),
    );

    expect(next?.bill.id).toBe("rent-2026-09");
    expect(next?.status.days).toBe(15);
  });

  it("adds and persists a custom one-off payment", () => {
    const added = addCustomBill({
      name: "Ubezpieczenie mieszkania",
      provider: "PZU",
      category: "Mieszkanie",
      amountCents: 12999,
      due: "2026-10-25",
      recurrence: "once",
      automatic: false,
    });

    const bill = listBills(new Date(2026, 8, 1)).find((entry) => entry.id === added.id);
    expect(bill).toMatchObject({
      name: "Ubezpieczenie mieszkania",
      provider: "PZU",
      amountCents: 12999,
      month: "2026-10",
      paid: false,
    });
    expect(JSON.parse(localStorage.getItem("todo-bills-v1")).customBills).toContainEqual(added);
  });

  it("creates and removes a custom monthly payment series", () => {
    const added = addCustomBill({
      name: "Karnet",
      category: "Subskrypcje",
      amountCents: 8900,
      due: "2026-01-31",
      recurrence: "monthly",
      endMonth: "2026-03",
      automatic: true,
    });

    const occurrences = listBills(new Date(2026, 0, 1))
      .filter((bill) => bill.customId === added.id);
    expect(occurrences.map((bill) => bill.due)).toEqual([
      "2026-01-31",
      "2026-02-28",
      "2026-03-31",
    ]);
    expect(getBillStatus(occurrences[0], new Date(2026, 0, 20)).key).toBe("automatic");

    expect(removeCustomBill(added.id)).toBe(true);
    expect(listBills(new Date(2026, 0, 1)).some((bill) => bill.customId === added.id)).toBe(false);
  });
});
