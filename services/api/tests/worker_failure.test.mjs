import { describe, expect, it } from 'vitest';
import { workerFailure } from '../app/worker_failure.mjs';

describe('worker error classification', () => {
  it('preserves remote disconnect uncertainty through nested fetch TypeErrors', () => {
    const socket = Object.assign(new Error('other side closed'), {code:'UND_ERR_SOCKET'});
    for (const error of [socket, new TypeError('terminated', {cause:socket}), new Error('Connection error', {cause:new TypeError('fetch failed', {cause:socket})})]) {
      expect(workerFailure(error)).toMatchObject({kind:'provider',submitted:true,billingCertainty:'unknown'});
      expect(workerFailure(error).message).toContain('model_stream_interrupted');
    }
  });
  it('keeps real programming failures distinct from transport failures', () => {
    expect(workerFailure(new TypeError("Cannot read properties of null (reading 'map')")))
      .toMatchObject({kind:'runtime',submitted:false,billingCertainty:'not_applicable'});
  });
  it('keeps the accepted response identifier when the stream terminates',()=>{
    expect(workerFailure(Object.assign(new TypeError('terminated',{cause:new Error('other side closed')}),
      {responseStarted:true,providerRequestId:'resp_original'}))).toMatchObject({
        kind:'provider',submitted:true,billingCertainty:'unknown',providerRequestId:'resp_original'});
  });
  it('retains explicit provider rejection and retry timing', () => {
    expect(workerFailure(Object.assign(new Error('too many requests'), {status:429,headers:new Headers({'retry-after':'12'})})))
      .toMatchObject({kind:'provider',submitted:false,billingCertainty:'not_submitted',retryAfter:12});
    expect(workerFailure(Object.assign(new Error('Forbidden'), {status:403})).kind).toBe('configuration');
    expect(workerFailure(Object.assign(new Error('socket closed'), {submitted:false,billingCertainty:'not_submitted'})))
      .toMatchObject({submitted:false,billingCertainty:'not_submitted'});
  });
});
