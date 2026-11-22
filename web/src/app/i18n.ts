import { createContext, useContext } from "react";
import type { RuleIssue } from "../sim/index.ts";
import type { Tyre } from "./compounds";
import type { Gap } from "./timing";

export const LANGS = ["en", "uk"] as const;
export type Lang = (typeof LANGS)[number];

/** A sentence that opens in bold: [bold, rest]. */
type Lead = [bold: string, rest: string];
type Channel = "speed_kmh" | "throttle" | "gear" | "brake";

const ukPlural = new Intl.PluralRules("uk");
/** Ukrainian picks one of three noun forms by the number: 1 коло, 2 кола, 5 кіл. */
const pl = (n: number, one: string, few: string, many: string) => {
  const form = ukPlural.select(n);
  return form === "one" ? one : form === "few" ? few : many;
};
const laps = (n: number) => pl(n, "коло", "кола", "кіл");
const races = (n: number) => pl(n, "гонку", "гонки", "гонок");

const enN = (x: number) => x.toLocaleString("en");

const EN_TYRES: Record<Tyre, string> = {
  soft: "soft",
  medium: "medium",
  hard: "hard",
  intermediate: "intermediate",
  wet: "wet",
  unknown: "unknown",
};

const en = {
  lang: "en" as Lang,
  n: enN,
  s: "s",
  km: "km",
  switchTo: "Українська",
  light: "Light",
  dark: "Dark",
  footer: "Unofficial project, not affiliated with Formula 1. Data from OpenF1.",
  tabs: {
    race: "Race",
    replay: "Replay",
    telemetry: "Telemetry",
    whatif: "What if",
    optimise: "Optimise",
    undercut: "Undercut",
    debrief: "Debrief",
    model: "Model card",
  },
  tyre: EN_TYRES,

  app: {
    loadingRaces: "Loading races",
    noRaces: "No races exported yet",
    noRacesBody: "Run the weekend pipeline to publish a bundle.",
    noSim: "No simulation for this race",
    noSimBody:
      "The strategy tools need this race’s model parameters, and it has none: it cannot be simulated (a wet race, or missing timing), or it is new and the model has not been refreshed with it yet. Race, replay and telemetry still work.",
    loadingSim: "Loading the simulation",
    noRaceState: (driver: string | null) => `No race state for ${driver ?? "this driver"}`,
    noRaceStateBody: "Pick a driver who started the race.",
    noReplay: "No replay for this race yet",
    noReplayBody:
      "Replay and telemetry start from the race’s fastest lap at pace. A wet race has none, and OpenF1 can be missing a lap’s location.",
    loadingReplay: "Loading the replay",
    loadingRace: "Loading the race",
    noTiming: "No lap timing for this race",
    noTimingBody: "The race state has no race times to place the cars by; telemetry still works.",
    race: "Race",
    driver: "Driver",
    raceViewOnly: " (race view only)",
    tools: "Tools",
  },

  failure: "That did not work",
  failureHint: "Reload the page to try again; if it keeps failing, the race bundle may be out of date.",
  assume: {
    rivals: ["Rivals keep their real strategies.", "They do not react to this plan."] as Lead,
    sampled: (lap: number): Lead => [
      "Safety cars, red flags and retirements are drawn at random",
      `after lap ${lap}, never replayed: only what was knowable at lap ${lap}.`,
    ],
    realised: [
      "Safety cars and red flags happen when they really did.",
      "That is hindsight: it says whether the plan worked out, not whether it was a good call.",
    ] as Lead,
    pace: (lap: number): Lead => ["Pace is fitted on the whole race,", `a known softening of the lap-${lap} view.`],
  },

  lap: "Lap",
  of: "of",
  lapOf: (lap: number, total: number) => `Lap ${lap} of ${total}`,
  stintLaps: (tyre: string, from: number, to: number) => `${tyre}, laps ${from} to ${to}`,
  handle: (k: number, lap: number) => `Stop ${k}, end of lap ${lap}. Arrow keys move it.`,
  toLap: (set: string, lap: number) => `${set} to lap ${lap}`,
  gap: (gap: Gap) => (!gap ? "" : "laps" in gap ? `+${gap.laps} lap${gap.laps > 1 ? "s" : ""}` : `+${gap.seconds.toFixed(1)}`),
  rule: (issue: RuleIssue) => {
    switch (issue.kind) {
      case "not-running":
        return `Not running after lap ${issue.fromLap}.`;
      case "pit-order":
        return `Pit laps must rise, after lap ${issue.fromLap} and before lap ${issue.total}.`;
      case "not-allocated":
        return `C${issue.compound} was not allocated for this race.`;
      case "compounds":
        return `Uses ${issue.used} dry compound; the rules need ${issue.need}.`;
      case "stops":
        return `Makes ${issue.made} stops; the rules need ${issue.need}.`;
      case "stint":
        return `Runs a ${issue.laps}-lap stint; the limit is ${issue.limit}.`;
    }
  },

  race: {
    title: (name: string, season: number, total: number) => `${name} ${season}, ${total} laps`,
    periodOne: (kind: string, lap: number) => `${kind} lap ${lap}`,
    periodRange: (kind: string, from: number, to: number) => `${kind} laps ${from} to ${to}`,
    pos: "Pos",
    driver: "Driver",
    team: "Team",
    stops: "Stops",
  },

  whatif: {
    from: (lap: number) => `Strategy from lap ${lap}`,
    decideAfter: "Decide after",
    actual: "Actual",
    alternative: "Alternative",
    actualLane: "Actual strategy",
    alternativeLane: "Alternative strategy; drag the stops",
    stop: "Stop",
    endOfLap: "End of lap",
    newSet: "New set",
    stopLap: (k: number) => `Stop ${k} lap`,
    stopCompound: (k: number) => `Stop ${k} compound`,
    remove: "Remove",
    addStop: "Add a stop",
    backToActual: "Back to the actual plan",
    disqualified: "The stewards would disqualify this plan, and so does the simulation:",
    legal: "Legal under this race’s rules.",
    events: "Safety cars and retirements",
    sampled: "Drawn at random",
    realised: "As they happened",
    run: (n: number) => `Run ${enN(n)} races`,
    finishing: "Finishing position",
    sameDraws: (n: number) => `${enN(n)} races, the same draws for both plans`,
    noResult: "No result yet",
    noResultBody: (n: number) =>
      `Edit the alternative, then run it: both plans race the same ${enN(n)} simulated races, and the difference is the answer.`,
    ahead: "of races the alternative finishes ahead",
    behind: "finishes behind",
    mean: (se: string) => `places on average, ±${se} (one standard error)`,
    expected: (name: string, p: string) => `${name}, average P${p}`,
    realFinish: (label: string) => `Real finish: ${label}`,
    simulating: (n: number) => `Simulating, ${enN(n)} races so far`,
  },

  histogram: {
    mostOften: (name: string, label: string) => `${name}: most often ${label}`,
    retired: "Ret",
  },

  optimise: {
    search: "Search",
    target: "Optimise for",
    position: "Position",
    podium: "Podium",
    points: "Points",
    beat: "Beat a rival",
    rival: "Rival",
    space: (maxStops: number, minStint: number, minClean: number) =>
      `0 to ${maxStops} stops in all, stints of ${minStint} laps or more, on compounds run for ${minClean} clean laps or more in this race.`,
    searching: "Searching",
    simulated: (n: number) => `${enN(n)} races simulated`,
    best: (lap: number) => `Best plans from lap ${lap}`,
    tried: (n: number, runs: number) =>
      `${enN(n)} plans tried; finalists raced ${enN(runs)} times on the same draws`,
    noSearch: "No search yet",
    noSearchBody: (keep: number) =>
      `Every legal plan races a few times; the better ones race again on more draws until ${keep} are left, then they race the actual plan.`,
    rank: "Rank",
    plan: "Plan",
    stops: "Stops",
    expected: "Expected position",
    win: "Win",
    beatRival: (driver: string) => `Beat ${driver}`,
    versusActual: "Places vs actual",
    spread: "P1 to P5, then the rest",
    actual: "Actual",
    notRunning: (driver: string, lap: number) => `${driver} is not running after lap ${lap}.`,
  },

  undercut: {
    title: "Undercut or overcut",
    attacks: (driver: string) => `${driver} attacks`,
    nobody: "Nobody to attack",
    notRunning: (driver: string) => `${driver} is not running at this point.`,
    defender: "Defender",
    stateAfter: "Race state after",
    fits: (driver: string) => `${driver} fits`,
    explain: (driver: string, lap: number) =>
      `Undercut: ${driver} pits at the end of lap ${lap}, the defender a lap later. Overcut: the other way round. Read once both have done their out-lap.`,
    run: (n: number) => `Run ${enN(n)} races each way`,
    ahead: "Who comes out ahead",
    noAnswer: "No answer yet",
    noAnswerBody: (driver: string) =>
      `Pick a defender and a lap: the answer is the chance ${driver} is ahead once both have stopped, and the parts it is made of.`,
    simulating: "Simulating",
    trust: ["How far to trust this: ", "the undercut check against real pit sequences", "."] as [string, string, string],
    undercutCaption: (driver: string, n: number) =>
      `${driver} ahead after pitting first, of ${enN(n)} races both finished the stops`,
    overcutCaption: (driver: string, n: number) => `${driver} ahead after staying out a lap longer, of ${enN(n)}`,
    parts: (lap: number) => `The parts, from posterior means at the start of lap ${lap}`,
    gap: "Gap",
    behindOf: (a: string, s: string, d: string) => `${a} ${s} behind ${d}`,
    aheadOf: (a: string, s: string, d: string) => `${a} ${s} ahead of ${d}`,
    pace: "Pace, tyres aside",
    paceValue: (x: string, driver: string) => `${x} s a lap for ${driver}`,
    newSet: "New set over old, on the out-lap",
    forDriver: (x: string, driver: string) => `${x} s for ${driver}`,
    greenStop: "Green pit stop",
    stopValue: (median: string, p10: string, p90: string) => `${median}, 80% between ${p10} and ${p90}`,
    warmup: "Warm-up, by lap on the new set",
  },

  debrief: {
    noMoreStops: "No more stops",
    stopFor: (lap: number, tyre: string) => `lap ${lap} for ${tyre}`,
    then: ", then ",
    stop: "Stop",
    stopCost: "The stop cost, places",
    planCost: "The plan from there cost",
    best: "Best plan: pit on",
    noneJudged: "No stops judged yet.",
    driver: "Driver",
    cost: "Cost, places",
    title: "Debrief",
    intro: (n: number) =>
      `Each stop is judged from the end of the lap before it, against the best plan the search finds from there, on ${enN(n)} fresh races. Twice: once with safety cars drawn at random, as the pit wall saw it, once with them where they fell.`,
    one: (driver: string) => `Debrief ${driver}`,
    field: "Debrief the whole field",
    judging: (driver: string) => `Judging ${driver}’s stops`,
    progress: (judged: number, total: number, n: number) =>
      `${judged} of ${total} drivers done, ${enN(n)} races simulated`,
    stopsOf: (driver: string) => `${driver}’s stops`,
    stopsSub: "expected places lost against the best plan; higher is worse",
    notJudged: "Not judged yet",
    notJudgedBody: (driver: string) => `Debrief ${driver} to see what each stop cost.`,
    noStops: "No stops to judge",
    noStopsBody: (driver: string) => `${driver} made no stop the search could judge.`,
    goodCall: "Was it a good call?",
    exAnte: "Ex ante: safety cars, red flags and retirements drawn at random after the decision lap.",
    workedOut: "Did it work out?",
    exPost: "Ex post: they happen when they really did. Hindsight, kept apart from the call.",
    rivals: ["Rivals keep their real strategies.", "The best plan is best against a field that does not react."] as Lead,
    costs: [
      "The stop cost",
      "compares the best plan with the best plan that makes this stop; later stops are charged to their own row.",
      "The plan cost",
      "is everything the real plan lost from that lap on.",
    ] as [string, string, string, string],
    pace: [
      "Pace is fitted on the whole race,",
      "a known softening of the ex ante view. Red figures are more than twice their standard error.",
    ] as Lead,
    swings: "Biggest strategic swings",
    judged: (judged: number, total: number) => `${judged} of ${total} drivers judged`,
    worstCalls: "Worst calls, ex ante",
    worstOutcomes: "Worst outcomes, ex post",
  },

  model: {
    title: "Model card",
    built: "Bundle built",
    code: "Code version",
    dataset: "Race dataset",
    schema: "Schema",
    era: "Era",
    draws: "Posterior draws",
    drawsValue: (n: number) => `${n}, one per simulated race`,
    pace: "Pace",
    paceWhole: "Fitted on the whole race.",
    fieldPace: (drivers: string) => ` Too few clean laps for ${drivers}: field pace instead.`,
    rules: "Rules",
    minCompounds: (n: number) => `${n} dry compounds at least`,
    minStops: (n: number) => `, ${n} stops at least`,
    maxStint: (n: number) => `, stints of ${n} laps at most`,
    simulation: "Simulation",
    noSim: "No simulation bundle for this race.",
    calibration: "Calibration on held-out races",
    loadingCalibration: "Loading calibration",
    noCalibration: "No calibration published",
    noCalibrationBody: "This bundle has none.",
    gatePassed: "The publish gate passed.",
    gateFailed: (reasons: string) => `The publish gate failed: ${reasons}.`,
    runs: (n: number, dataset: string) => `${enN(n)} races per car-start, dataset ${dataset}.`,
    segment: "Segment",
    races: "Races",
    carStarts: "Car-starts",
    inside50: "Inside 50% band",
    inside80: "Inside 80% band",
    logScore: "Log score",
    asStarted: "Finish as started",
    note: "Calibrated means 50% and 80% of real finishes fall inside the 50% and 80% bands. A higher log score is better; the last column is the baseline that every car finishes where it started. Per-track scores are not exported yet: the era and passing rows are the nearest.",
    pit: "Where real finishes fell in the simulated spread",
    pitLabel: "PIT histogram: flat when calibrated",
    flat: "Flat is calibrated; a U shape is overconfident. ",
    fails: "Where the simulator fails",
    segmentName: (segment: string) => segment,
  },

  replay: {
    red: "Red flag",
    sc: "Safety car",
    vsc: "Virtual safety car",
    green: "Green",
    redBand: "Red",
    map: (lap: number) => `Track map, every car on lap ${lap}`,
    time: "Race time",
    play: "Play",
    pause: "Pause",
    again: "Replay",
    speed: "Speed",
    ticks: (driver: string) => `Ticks mark ${driver}'s stops. `,
    line: (driver: string, lap: number) =>
      `Cars run on official lap times along the fastest lap's line (${driver}, lap ${lap}); inside a lap, and through the pit lane, their position is an estimate.`,
    order: "Order",
    gapNote: "gap at the last line crossed",
    gap: "Gap",
    tyre: "Tyre",
    out: "Out",
    pit: "Pit",
  },

  telemetry: {
    noData: "No car data for this race",
    noDataBody: "OpenF1 has no car data for these laps.",
    fastest: "Fastest laps",
    byDistance: "by distance from the line",
    driver: "Driver",
    against: "Against",
    option: (driver: string, lap: number, time: string) => `${driver}, lap ${lap}, ${time}`,
    onlyOne: "Only one driver has car data for this race.",
    loading: "Loading telemetry",
    lapN: (lap: number) => `lap ${lap}`,
    versus: (b: string, a: string) => `${b} against ${a}, s`,
    point: "Point at the charts to read both laps at one place on track.",
    reading: (driver: string, speed: number, throttle: number, gear: number, braking: boolean) =>
      `${driver} ${speed} km/h, ${throttle}% throttle, gear ${gear}${braking ? ", braking" : ""}`,
    gapReading: (driver: string, behind: boolean, s: string) => `${driver} ${behind ? "behind" : "ahead"} by ${s} s`,
    speed: "Speed, km/h",
    throttle: "Throttle, %",
    brake: (a: string, b: string) => `Brake, ${a} then ${b}`,
    gear: "Gear",
    gapTitle: (driver: string) => `Gap, s: above the line ${driver} is behind`,
    gapLabel: (b: string, a: string) => `Gap of ${b} to ${a} by distance`,
    trace: (channel: Channel, drivers: readonly string[]) =>
      `${channel.split("_")[0]} by distance, ${drivers.join(" and ")}`,
    note: "Car data from OpenF1 at about four samples a second; brake is on or off. Distance integrates speed, so a corner can sit a few metres apart on the two laps.",
    where: "Who was faster where",
    minisectors: (n: number) => `${n} minisectors of equal length`,
    mapLabel: (a: string, b: string) => `Minisectors coloured by the faster of ${a} and ${b}`,
    fasterIn: (n: number, s: string) => `faster in ${n}, gaining ${s} s`,
    largest: "Largest differences",
    minisector: "Minisector",
    fromKm: "From, km",
    faster: "Faster",
    by: "By, s",
    sectorsNote: (km: string) =>
      `The circle marks the line. Minisectors split ${km} km of each lap evenly and are laid on the map by path length.`,
  },
};

export type Strings = typeof en;

const ukN = (x: number) => x.toLocaleString("uk");

const UK_SEGMENT_KEYS: Record<string, string> = {
  start: "старт",
  era: "ера",
  "neutralised after start": "нейтралізація після старту",
  passing: "обгони",
};
const UK_SEGMENT_VALUES: Record<string, string> = {
  no: "ні",
  yes: "так",
  hard: "важкі",
  medium: "середні",
  easy: "легкі",
};

/** Calibration segments arrive as "key: value" in English; unknown ones are shown as they come. */
function ukSegment(segment: string): string {
  if (segment === "all") return "усі";
  const [key, value] = segment.split(": ");
  if (!key || !value || !(key in UK_SEGMENT_KEYS)) return segment;
  const translated =
    UK_SEGMENT_VALUES[value] ??
    value.replace(/^after lap (\d+)$/, "після кола $1").replace(/^(\d+)% distance$/, "$1% дистанції");
  return `${UK_SEGMENT_KEYS[key]}: ${translated}`;
}

const uk: Strings = {
  lang: "uk",
  n: ukN,
  s: "с",
  km: "км",
  switchTo: "English",
  light: "Світла",
  dark: "Темна",
  footer: "Неофіційний проєкт, не пов’язаний із Formula 1. Дані з OpenF1.",
  tabs: {
    race: "Гонка",
    replay: "Повтор",
    telemetry: "Телеметрія",
    whatif: "Що якби",
    optimise: "Оптимізація",
    undercut: "Андеркат",
    debrief: "Розбір",
    model: "Картка моделі",
  },
  tyre: {
    soft: "м’яка",
    medium: "середня",
    hard: "жорстка",
    intermediate: "проміжна",
    wet: "дощова",
    unknown: "невідома",
  },

  app: {
    loadingRaces: "Завантаження гонок",
    noRaces: "Ще немає експортованих гонок",
    noRacesBody: "Запустіть конвеєр вихідних, щоб опублікувати пакет.",
    noSim: "Для цієї гонки немає симуляції",
    noSimBody:
      "Інструментам стратегії потрібні параметри моделі для цієї гонки, а їх немає: її неможливо змоделювати (мокра гонка або бракує хронометражу), або вона нова й модель ще не оновили з нею. Гонка, повтор і телеметрія працюють.",
    loadingSim: "Завантаження симуляції",
    noRaceState: (driver) => `Немає стану гонки для ${driver ?? "цього гонщика"}`,
    noRaceStateBody: "Виберіть гонщика, який стартував у гонці.",
    noReplay: "Повтору для цієї гонки ще немає",
    noReplayBody:
      "Повтор і телеметрія будуються від найшвидшого кола гонки в повному темпі. У мокрій гонці такого кола немає, а в OpenF1 може бракувати даних про розташування на колі.",
    loadingReplay: "Завантаження повтору",
    loadingRace: "Завантаження гонки",
    noTiming: "Немає хронометражу кіл для цієї гонки",
    noTimingBody: "У стані гонки немає часу, за яким можна розставити боліди; телеметрія працює.",
    race: "Гонка",
    driver: "Гонщик",
    raceViewOnly: " (лише перегляд гонки)",
    tools: "Інструменти",
  },

  failure: "Не вдалося",
  failureHint: "Перезавантажте сторінку, щоб спробувати ще раз; якщо помилка повторюється, пакет гонки може бути застарілим.",
  assume: {
    rivals: ["Суперники дотримуються своїх реальних стратегій.", "Вони не реагують на цей план."],
    sampled: (lap) => [
      "Автомобілі безпеки, червоні прапори та сходи розігруються випадково",
      `після кола ${lap} і ніколи не відтворюються: лише те, що було відомо на колі ${lap}.`,
    ],
    realised: [
      "Автомобілі безпеки та червоні прапори з’являються тоді, коли це сталося насправді.",
      "Це погляд заднім числом: він показує, чи спрацював план, а не чи було рішення добрим.",
    ],
    pace: (lap) => ["Темп підібрано за всією гонкою,", `і це відоме пом’якшення погляду з кола ${lap}.`],
  },

  lap: "Коло",
  of: "з",
  lapOf: (lap, total) => `Коло ${lap} з ${total}`,
  stintLaps: (tyre, from, to) => `${tyre}, кола ${from}–${to}`,
  handle: (k, lap) => `Зупинка ${k}, кінець кола ${lap}. Стрілки її пересувають.`,
  toLap: (set, lap) => `${set} до кола ${lap}`,
  gap: (gap) => (!gap ? "" : "laps" in gap ? `+${gap.laps} ${laps(gap.laps)}` : `+${gap.seconds.toFixed(1)}`),
  rule: (issue) => {
    switch (issue.kind) {
      case "not-running":
        return `Не на трасі після кола ${issue.fromLap}.`;
      case "pit-order":
        return `Кола піт-стопів мають зростати: після кола ${issue.fromLap} і до кола ${issue.total}.`;
      case "not-allocated":
        return `C${issue.compound} не виділено на цю гонку.`;
      case "compounds":
        return `Сухих сумішей: ${issue.used}; правила вимагають ${issue.need}.`;
      case "stops":
        return `Зупинок: ${issue.made}; правила вимагають ${issue.need}.`;
      case "stint":
        return `Стинт на ${issue.laps} ${laps(issue.laps)}; межа — ${issue.limit}.`;
    }
  },

  race: {
    title: (name, season, total) => `${name} ${season}, ${total} ${laps(total)}`,
    periodOne: (kind, lap) => `${kind} на колі ${lap}`,
    periodRange: (kind, from, to) => `${kind} на колах ${from}–${to}`,
    pos: "Поз.",
    driver: "Гонщик",
    team: "Команда",
    stops: "Зупинки",
  },

  whatif: {
    from: (lap) => `Стратегія з кола ${lap}`,
    decideAfter: "Рішення після",
    actual: "Реальна",
    alternative: "Альтернатива",
    actualLane: "Реальна стратегія",
    alternativeLane: "Альтернативна стратегія; перетягуйте зупинки",
    stop: "Зупинка",
    endOfLap: "Наприкінці кола",
    newSet: "Новий комплект",
    stopLap: (k) => `Коло зупинки ${k}`,
    stopCompound: (k) => `Суміш зупинки ${k}`,
    remove: "Прибрати",
    addStop: "Додати зупинку",
    backToActual: "Повернути реальний план",
    disqualified: "Стюарди дискваліфікували б за такий план, і симуляція теж дискваліфікує:",
    legal: "Відповідає правилам цієї гонки.",
    events: "Автомобілі безпеки та сходи",
    sampled: "Випадкові",
    realised: "Як було насправді",
    run: (n) => `Змоделювати ${ukN(n)} ${races(n)}`,
    finishing: "Фінішна позиція",
    sameDraws: (n) => `Гонок: ${ukN(n)}, однакові вибірки для обох планів`,
    noResult: "Результату ще немає",
    noResultBody: (n) =>
      `Змініть альтернативу й запустіть її: обидва плани проходять ту саму серію з ${ukN(n)} змодельованих гонок, а відповідь — це різниця між ними.`,
    ahead: "гонок альтернатива фінішує попереду",
    behind: "фінішує позаду",
    mean: (se) => `позиції в середньому, ±${se} (одна стандартна похибка)`,
    expected: (name, p) => `${name}, у середньому P${p}`,
    realFinish: (label) => `Фініш насправді: ${label}`,
    simulating: (n) => `Симуляція триває, гонок уже: ${ukN(n)}`,
  },

  histogram: {
    mostOften: (name, label) => `${name}: найчастіше ${label}`,
    retired: "Сх",
  },

  optimise: {
    search: "Пошук",
    target: "Ціль",
    position: "Позиція",
    podium: "Подіум",
    points: "Очки",
    beat: "Обійти суперника",
    rival: "Суперник",
    space: (maxStops, minStint, minClean) =>
      `Загалом від 0 до ${maxStops} ${pl(maxStops, "зупинки", "зупинок", "зупинок")}, стинти щонайменше по ${minStint} ${laps(minStint)}, лише на сумішах, що проїхали в цій гонці щонайменше ${minClean} чистих ${pl(minClean, "коло", "кола", "кіл")}.`,
    searching: "Пошук триває",
    simulated: (n) => `Змодельовано гонок: ${ukN(n)}`,
    best: (lap) => `Найкращі плани з кола ${lap}`,
    tried: (n, runs) =>
      `Перевірено планів: ${ukN(n)}; фіналісти пройшли по ${ukN(runs)} ${pl(runs, "гонці", "гонки", "гонок")} на однакових вибірках`,
    noSearch: "Пошуку ще не було",
    noSearchBody: (keep) =>
      `Кожен дозволений план проходить кілька гонок; кращі змагаються знову на більшій кількості вибірок, доки не залишиться ${keep}, а тоді змагаються з реальним планом.`,
    rank: "Місце",
    plan: "План",
    stops: "Зупинки",
    expected: "Очікувана позиція",
    win: "Перемога",
    beatRival: (driver) => `Обійти ${driver}`,
    versusActual: "Позицій проти реального",
    spread: "P1–P5, далі решта",
    actual: "Реальний",
    notRunning: (driver, lap) => `${driver} не на трасі після кола ${lap}.`,
  },

  undercut: {
    title: "Андеркат чи оверкат",
    attacks: (driver) => `${driver} атакує`,
    nobody: "Нема кого атакувати",
    notRunning: (driver) => `${driver} на цей момент не на трасі.`,
    defender: "Захисник",
    stateAfter: "Стан гонки після",
    fits: (driver) => `${driver} ставить`,
    explain: (driver, lap) =>
      `Андеркат: ${driver} заїжджає на піт-стоп наприкінці кола ${lap}, захисник — на коло пізніше. Оверкат: навпаки. Результат зчитується, коли обидва проїдуть коло виїзду.`,
    run: (n) => `Змоделювати по ${ukN(n)} ${pl(n, "гонці", "гонки", "гонок")} для кожного варіанта`,
    ahead: "Хто виїде попереду",
    noAnswer: "Відповіді ще немає",
    noAnswerBody: (driver) =>
      `Виберіть захисника й коло: відповідь — імовірність того, що ${driver} буде попереду, коли обидва зупиняться, і складники цієї відповіді.`,
    simulating: "Симуляція",
    trust: ["Наскільки цьому довіряти: ", "перевірка андеркату на реальних послідовностях піт-стопів", "."],
    undercutCaption: (driver, n) =>
      `${driver} попереду, заїхавши першим; з ${ukN(n)} ${pl(n, "гонки", "гонок", "гонок")}, у яких обидва завершили зупинки`,
    overcutCaption: (driver, n) => `${driver} попереду, залишившись на трасі на коло довше; з ${ukN(n)}`,
    parts: (lap) => `Складники, за апостеріорними середніми на початку кола ${lap}`,
    gap: "Відрив",
    behindOf: (a, s, d) => `${a} на ${s} позаду ${d}`,
    aheadOf: (a, s, d) => `${a} на ${s} попереду ${d}`,
    pace: "Темп без урахування шин",
    paceValue: (x, driver) => `${x} с за коло для ${driver}`,
    newSet: "Новий комплект проти старого на колі виїзду",
    forDriver: (x, driver) => `${x} с для ${driver}`,
    greenStop: "Піт-стоп під зеленим прапором",
    stopValue: (median, p10, p90) => `${median}, 80% між ${p10} і ${p90}`,
    warmup: "Прогрів, за колами на новому комплекті",
  },

  debrief: {
    noMoreStops: "Більше жодних зупинок",
    stopFor: (lap, tyre) => `коло ${lap} на ${tyre}`,
    then: ", потім ",
    stop: "Зупинка",
    stopCost: "Ціна зупинки, позицій",
    planCost: "Ціна плану звідти",
    best: "Найкращий план: піт-стоп на",
    noneJudged: "Ще жодної оціненої зупинки.",
    driver: "Гонщик",
    cost: "Ціна, позицій",
    title: "Розбір",
    intro: (n) =>
      `Кожну зупинку оцінено з кінця попереднього кола проти найкращого плану, який пошук знаходить звідти, на ${ukN(n)} нових гонках. Двічі: раз із випадковими автомобілями безпеки, як це бачив піт-уол, і раз — там, де вони сталися насправді.`,
    one: (driver) => `Розібрати ${driver}`,
    field: "Розібрати все поле",
    judging: (driver) => `Оцінюємо зупинки ${driver}`,
    progress: (judged, total, n) => `Готово ${judged} з ${total} гонщиків, змодельовано гонок: ${ukN(n)}`,
    stopsOf: (driver) => `Зупинки ${driver}`,
    stopsSub: "очікувано втрачені позиції проти найкращого плану; більше — гірше",
    notJudged: "Ще не оцінено",
    notJudgedBody: (driver) => `Розберіть ${driver}, щоб побачити ціну кожної зупинки.`,
    noStops: "Немає зупинок для оцінки",
    noStopsBody: (driver) => `У ${driver} немає зупинок, які міг би оцінити пошук.`,
    goodCall: "Чи було рішення добрим?",
    exAnte: "Ex ante: автомобілі безпеки, червоні прапори та сходи розігруються випадково після кола рішення.",
    workedOut: "Чи спрацювало?",
    exPost: "Ex post: вони стаються тоді, коли сталися насправді. Погляд заднім числом, окремо від рішення.",
    rivals: ["Суперники дотримуються своїх реальних стратегій.", "Найкращий план — найкращий проти поля, яке не реагує."],
    costs: [
      "Ціна зупинки",
      "порівнює найкращий план із найкращим планом, що містить цю зупинку; пізніші зупинки враховано в їхніх власних рядках.",
      "Ціна плану",
      "— це все, що реальний план утратив від того кола.",
    ],
    pace: [
      "Темп підібрано за всією гонкою,",
      "і це відоме пом’якшення погляду ex ante. Червоні значення перевищують свою стандартну похибку більш ніж удвічі.",
    ],
    swings: "Найдорожчі стратегічні рішення",
    judged: (judged, total) => `Оцінено ${judged} з ${total} гонщиків`,
    worstCalls: "Найгірші рішення, ex ante",
    worstOutcomes: "Найгірші наслідки, ex post",
  },

  model: {
    title: "Картка моделі",
    built: "Пакет зібрано",
    code: "Версія коду",
    dataset: "Набір даних гонки",
    schema: "Схема",
    era: "Ера",
    draws: "Апостеріорні вибірки",
    drawsValue: (n) => `${n}, по одній на змодельовану гонку`,
    pace: "Темп",
    paceWhole: "Підібрано за всією гонкою.",
    fieldPace: (drivers) => ` Замало чистих кіл для ${drivers}: замість цього темп поля.`,
    rules: "Правила",
    minCompounds: (n) => `сухих сумішей — щонайменше ${n}`,
    minStops: (n) => `, зупинок — щонайменше ${n}`,
    maxStint: (n) => `, стинти — щонайбільше ${n} ${laps(n)}`,
    simulation: "Симуляція",
    noSim: "Для цієї гонки немає пакета симуляції.",
    calibration: "Калібрування на відкладених гонках",
    loadingCalibration: "Завантаження калібрування",
    noCalibration: "Калібрування не опубліковано",
    noCalibrationBody: "У цьому пакеті його немає.",
    gatePassed: "Перевірку перед публікацією пройдено.",
    gateFailed: (reasons) => `Перевірку перед публікацією не пройдено: ${reasons}.`,
    runs: (n, dataset) => `${ukN(n)} ${pl(n, "гонка", "гонки", "гонок")} на кожен старт боліда, набір даних ${dataset}.`,
    segment: "Сегмент",
    races: "Гонки",
    carStarts: "Старти болідів",
    inside50: "У межах 50% смуги",
    inside80: "У межах 80% смуги",
    logScore: "Лог-оцінка",
    asStarted: "Фініш як на старті",
    note: "Калібрована модель означає, що 50% і 80% реальних фінішів потрапляють у 50% і 80% смуги. Вища лог-оцінка краща; останній стовпець — базова модель, за якою кожен болід фінішує там, де стартував. Оцінок окремо за трасами ще не експортовано: найближчі до них — рядки ери та обгонів.",
    pit: "Куди реальні фініші потрапили в змодельованому розкиді",
    pitLabel: "PIT-гістограма: рівна, коли модель калібрована",
    flat: "Рівна — калібрована; U-подібна — надмірно впевнена. ",
    fails: "Де симулятор помиляється",
    segmentName: ukSegment,
  },

  replay: {
    red: "Червоний прапор",
    sc: "Автомобіль безпеки",
    vsc: "Віртуальний автомобіль безпеки",
    green: "Зелений прапор",
    redBand: "Черв.",
    map: (lap) => `Карта траси: усі боліди на колі ${lap}`,
    time: "Час гонки",
    play: "Відтворити",
    pause: "Пауза",
    again: "Ще раз",
    speed: "Швидкість",
    ticks: (driver) => `Позначки — зупинки ${driver}. `,
    line: (driver, lap) =>
      `Боліди рухаються за офіційним часом кіл траєкторією найшвидшого кола (${driver}, коло ${lap}); усередині кола й на піт-лейні їхнє положення — оцінка.`,
    order: "Порядок",
    gapNote: "відрив на останньому перетині лінії",
    gap: "Відрив",
    tyre: "Шина",
    out: "Сход",
    pit: "Піт",
  },

  telemetry: {
    noData: "Немає даних болідів для цієї гонки",
    noDataBody: "В OpenF1 немає даних болідів для цих кіл.",
    fastest: "Найшвидші кола",
    byDistance: "за відстанню від лінії",
    driver: "Гонщик",
    against: "Проти",
    option: (driver, lap, time) => `${driver}, коло ${lap}, ${time}`,
    onlyOne: "Лише один гонщик має дані боліда для цієї гонки.",
    loading: "Завантаження телеметрії",
    lapN: (lap) => `коло ${lap}`,
    versus: (b, a) => `${b} проти ${a}, с`,
    point: "Наведіть на графіки, щоб порівняти обидва кола в одній точці траси.",
    reading: (driver, speed, throttle, gear, braking) =>
      `${driver} ${speed} км/год, газ ${throttle}%, передача ${gear}${braking ? ", гальмує" : ""}`,
    gapReading: (driver, behind, s) => `${driver} ${behind ? "позаду" : "попереду"} на ${s} с`,
    speed: "Швидкість, км/год",
    throttle: "Газ, %",
    brake: (a, b) => `Гальмо: спершу ${a}, потім ${b}`,
    gear: "Передача",
    gapTitle: (driver) => `Відрив, с: вище лінії ${driver} позаду`,
    gapLabel: (b, a) => `Відрив ${b} від ${a} за відстанню`,
    trace: (channel, drivers) =>
      `${{ speed_kmh: "Швидкість", throttle: "Газ", gear: "Передача", brake: "Гальмо" }[channel]} за відстанню, ${drivers.join(" і ")}`,
    note: "Дані болідів з OpenF1, приблизно чотири вибірки на секунду; гальмо лише ввімкнене або вимкнене. Відстань отримано інтегруванням швидкості, тож поворот на двох колах може розходитися на кілька метрів.",
    where: "Хто де був швидшим",
    minisectors: (n) => `Мінісекторів однакової довжини: ${n}`,
    mapLabel: (a, b) => `Мінісектори, розфарбовані за швидшим із ${a} і ${b}`,
    fasterIn: (n, s) => `швидший у ${n}, виграш ${s} с`,
    largest: "Найбільші різниці",
    minisector: "Мінісектор",
    fromKm: "Від, км",
    faster: "Швидший",
    by: "На, с",
    sectorsNote: (km) =>
      `Кружок позначає лінію. Мінісектори рівномірно ділять ${km} км кожного кола й накладені на карту за довжиною шляху.`,
  },
};

export const STRINGS: Record<Lang, Strings> = { en, uk };

const STORAGE_KEY = "lang";

/** The viewer's saved choice, else Ukrainian for a browser that asks for it, else English. */
export function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "uk") return saved;
  } catch {
    // Storage can be blocked; fall back to the browser's languages.
  }
  return navigator.languages.some((l) => l.toLowerCase().startsWith("uk")) ? "uk" : "en";
}

export function saveLang(lang: Lang) {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Storage can be blocked; the choice then lasts until reload.
  }
}

export const I18n = createContext<{ t: Strings; setLang: (lang: Lang) => void }>({
  t: en,
  setLang: () => undefined,
});

export const useT = () => useContext(I18n).t;
