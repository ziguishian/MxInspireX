export const CREATOR_POEM = `山海未曾催远客，
微光先落画中枝。
一笔一程皆有信，
风来正是启航时。`;

export const CREATOR_ENCOURAGEMENT = '别急，你正在把想象变成世界；再往前一步，答案就会亮起来。';

type ConsoleWriter = (message?: unknown, ...optionalParams: unknown[]) => void;

export function printConsoleEasterEgg(write: ConsoleWriter = console.log.bind(console)) {
  write(
    '%c MXINSPIREX · 写给创造者 ',
    'padding:7px 11px;border:1px solid #6f8e78;border-radius:8px;background:#152019;color:#d6ff4b;font-size:14px;font-weight:700;letter-spacing:.12em;',
  );
  write(
    `%c${CREATOR_POEM}`,
    'padding:9px 12px;color:#6f8e78;font-size:13px;line-height:1.9;',
  );
  write(
    `%c ✦ ${CREATOR_ENCOURAGEMENT} `,
    'padding:7px 11px;border-radius:999px;background:#d6ff4b;color:#152019;font-size:12px;font-weight:700;',
  );
}
