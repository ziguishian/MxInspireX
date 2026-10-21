import { describe, expect, it } from 'vitest';
import { localServiceHint, serviceNetworkHint, taskIssue } from './taskErrors';
import { generationFailureText, publicAssistantMessage } from './generationErrors';
import { designSteps } from '../designPresentation';

describe('network recovery guidance', () => {
  it('explains unsubmitted audio and video configuration failures', () => {
    expect(taskIssue('Failed to run function tools: 请先选择支持语音生成的音频模型')).toMatchObject({ code: 'audio_model', action: 'settings' });
    expect(taskIssue('video 模型 bytedance/seedance-2.5 不在本地目录中')).toMatchObject({ code: 'video_model', action: 'settings' });
  });
  it('explains a dropped model stream without blaming the brief or claiming no charge', () => {
    for (const raw of ['other side closed', 'TypeError: terminated UND_ERR_SOCKET', 'model_stream_interrupted']) {
      const issue = taskIssue(raw);
      expect(issue).toMatchObject({code:'model_stream_interrupted',action:'inspect'});
      expect(issue.message).toContain('费用尚未确认');
      expect(issue.message).not.toMatch(/修改要求|切换网络|未计费/);
    }
  });
  it('shows output truncation and incomplete Responses without claiming a network failure', () => {
    expect(taskIssue('model_output_limit：模型输出达到单次长度上限')).toMatchObject({code:'model_output_limit',action:'inspect'});
    expect(taskIssue('OpenAI Responses request ended with unsuccessful terminal state "response.incomplete".')).toMatchObject({code:'model_response_incomplete',action:'inspect'});
    expect(taskIssue('model_output_limit').message).toContain('停止自动重发');
  });
  it.each([
    'Connection error.', 'APIConnectionError: Connection error.', 'getaddrinfo ENOTFOUND relay.test',
    'EAI_AGAIN', 'ENETUNREACH', 'EHOSTUNREACH', 'TypeError: fetch failed', 'Failed to fetch',
    '模型探测失败：<urlopen error [Errno 8] nodename nor servname provided, or not known>',
    '模型暂时不可用：连接超时，请检查 API Key', 'HTTP 504 Gateway Timeout',
    'HTTP 403: unsupported_country_region_territory', 'HTTP 403: This service is not available in your country',
    '当前地区不支持访问', { detail: { error: { code: 'unsupported_country_region_territory', message: 'Forbidden' } } },
    JSON.stringify({ error: { message: 'Connection error.' } }),
  ])('identifies transport and regional access failures: %s', error => {
    const issue = taskIssue(error);
    expect(issue.code).toBe('network');
    expect(issue.message).toContain(serviceNetworkHint);
    expect(issue.message).not.toMatch(/API Key|模型设置|模型配置/);
    expect(issue.action).toBe('resume');
    expect(issue.actionLabel).toContain('已切换网络');
  });

  it.each([
    ['HTTP 401 invalid API key', 'auth'], ['API Key 未保存', 'auth'],
    ['HTTP 403 permission denied for model', 'permission'], ['HTTP 429 too many requests', 'rate'],
    ['insufficient_quota', 'quota'], ['unsupported reasoning_effort', 'model'],
    ['model not found', 'model'], [localServiceHint, 'local_service'],
  ])('keeps a specific recovery action for %s', (error, code) => {
    const issue = taskIssue(error);
    expect(issue.code).toBe(code);
    expect(issue.message).not.toContain('海外');
  });

  it('separates an unavailable image route from a Luna text-model failure', () => {
    const issue = taskIssue('没有可用且兼容的自动图像模型；请同步本地模型目录或手动选择模型');
    expect(issue).toMatchObject({ code: 'image_model', title: '自动图像模型不可用', action: 'settings' });
    expect(issue.message).toContain('文本 Agent 已正常运行');
    expect(issue.actionLabel).toBe('检查图像模型设置');
  });

  it('uses the same guidance in media failures, assistant replies and progress', () => {
    expect(generationFailureText(new Error('Connection error.'))).toBe(serviceNetworkHint);
    expect(publicAssistantMessage('已有图片已保存。\n\nConnection error.')).toBe(`已有图片已保存。\n\n${serviceNetworkHint}`);
    const labels = designSteps([{ phase: 'tool', message: '调用工具：generate_image' },
      { phase: 'error', message: '工具失败：generate_image · getaddrinfo ENOTFOUND relay.test' }], 'running').map(step => step.label).join('\n');
    expect(labels).toContain(serviceNetworkHint);
    expect(labels).not.toMatch(/relay.test|ENOTFOUND|模型设置/);
  });
});

 it("does not blame the user brief for internal tool argument failures", () => {
   expect(taskIssue("工具参数校验未通过：当前阶段已停止重复修正同一错误")).toMatchObject({code:"tool_arguments",action:"inspect"});
   expect(taskIssue("工具参数校验未通过").message).toContain("无需改写设计要求");
 });
