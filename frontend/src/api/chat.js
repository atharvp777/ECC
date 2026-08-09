import { api } from './client';

export const chat = (messages) => 
  api.post('/api/chat/', messages);
