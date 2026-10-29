// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { useEffect, useRef, useState } from 'react';

import { getCore } from 'cvat-core-wrapper';

const core = getCore();

const DEBOUNCE_MS = 500;
const BASE_RETRY_MS = 1000;
const MAX_RETRY_MS = 30000;

export type LiveStatus = 'connecting' | 'live' | 'reconnecting';

export default function useLiveLabelCounts(taskId: number, onChange: () => void): LiveStatus {
    const [status, setStatus] = useState<LiveStatus>('connecting');
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;

    useEffect(() => {
        if (!Number.isInteger(taskId)) {
            return undefined;
        }

        let socket: WebSocket | null = null;
        let retryTimer: ReturnType<typeof setTimeout> | null = null;
        let debounceTimer: ReturnType<typeof setTimeout> | null = null;
        let attempt = 0;
        let disposed = false;

        const scheduleReconnect = (): void => {
            if (disposed || retryTimer !== null) {
                return;
            }

            setStatus('reconnecting');
            const delay = Math.min(BASE_RETRY_MS * 2 ** attempt, MAX_RETRY_MS);
            attempt += 1;
            retryTimer = setTimeout(() => {
                retryTimer = null;
                // eslint-disable-next-line no-use-before-define
                connect();
            }, delay);
        };

        const connect = async (): Promise<void> => {
            try {
                const { ticket } = await core.analytics.labelCounts.liveTicket({ taskID: taskId });
                if (disposed) {
                    return;
                }

                const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
                const url = `${scheme}://${window.location.host}/api/label-counts/live?ticket=${ticket}`;
                const ws = new WebSocket(url);
                socket = ws;

                ws.onopen = () => {
                    setStatus('live');
                    if (attempt > 0) {
                        // some changes may have been missed while disconnected
                        onChangeRef.current();
                    }
                    attempt = 0;
                };
                ws.onmessage = (event: MessageEvent) => {
                    try {
                        if (JSON.parse(event.data).type !== 'changed') {
                            return;
                        }
                    } catch {
                        return;
                    }

                    if (debounceTimer !== null) {
                        clearTimeout(debounceTimer);
                    }
                    debounceTimer = setTimeout(() => {
                        debounceTimer = null;
                        onChangeRef.current();
                    }, DEBOUNCE_MS);
                };
                ws.onerror = scheduleReconnect;
                ws.onclose = scheduleReconnect;
            } catch {
                scheduleReconnect();
            }
        };

        connect();

        return () => {
            disposed = true;
            if (retryTimer !== null) {
                clearTimeout(retryTimer);
            }
            if (debounceTimer !== null) {
                clearTimeout(debounceTimer);
            }
            if (socket) {
                socket.onopen = null;
                socket.onmessage = null;
                socket.onerror = null;
                socket.onclose = null;
                socket.close();
            }
        };
    }, [taskId]);

    return status;
}
