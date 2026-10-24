// Remember consumed inputs even after the user deletes their visible text.
export function mergeVisibleInputs(prompt: string, seen: Record<string, string>, inputs: [string, string][]) {
  const next = { ...seen };
  for (const [key, value] of inputs) {
    if (next[key] === value) continue;
    const previous = next[key];
    if (previous && prompt.includes(previous)) prompt = prompt.replace(previous, value);
    else if (value && !prompt.includes(value)) prompt += `${prompt ? '\n\n' : ''}${value}`;
    next[key] = value;
  }
  for (const key of Object.keys(next)) {
    if (!inputs.some(([id]) => id === key)) {
      if (next[key]) prompt = prompt.replace(next[key], '');
      delete next[key];
    }
  }
  return { prompt, seen: next };
}
