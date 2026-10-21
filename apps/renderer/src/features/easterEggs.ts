const cosmicQuestionPatterns = [
  '这个世界会被设计成什么样',
  '世界会被设计成什么样',
  '未来会怎么样',
  '未来会变成什么样',
  '未来是什么样',
];

export function isCosmicFutureQuestion(text: string): boolean {
  const compact = text.toLocaleLowerCase().replace(/[\s，。！？!?、,.；;：:"'“”‘’（）()]+/g, '');
  return cosmicQuestionPatterns.some(pattern => compact.includes(pattern));
}
