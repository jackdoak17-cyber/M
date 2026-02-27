import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

export const config = {
  auth: false,
}

const BOT_TOKEN =
  Deno.env.get('TELEGRAM_BOT_TOKEN') ?? Deno.env.get('ODDS_ANALYST_X_POST_BOT_TOKEN')
const TELEGRAM_API = BOT_TOKEN ? `https://api.telegram.org/bot${BOT_TOKEN}` : ''

Deno.serve(async (req) => {
  if (req.method !== 'POST') {
    return new Response('ok', { status: 200 })
  }

  const body = await req.json()
  const cq = body?.callback_query
  if (!cq) return new Response('ok', { status: 200 })

  const callbackQueryId = cq.id
  const data: string = cq.data ?? ''
  const chatId = cq.message?.chat?.id
  const messageId = cq.message?.message_id

  // Parse callback_data: "approve:post_type:YYYY-MM-DD" or "reject:..."
  const parts = data.split(':')
  if (parts.length !== 3 || !['approve', 'reject'].includes(parts[0])) {
    return new Response('ok', { status: 200 })
  }

  const [action, postType, postDate] = parts
  const newStatus = action === 'approve' ? 'approved' : 'rejected'
  const label = action === 'approve'
    ? '✅ Approved — will post at scheduled time'
    : '❌ Rejected — post cancelled'

  // Answer immediately — clears Telegram's spinner with a short confirmation
  if (TELEGRAM_API) {
    await fetch(`${TELEGRAM_API}/answerCallbackQuery`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        callback_query_id: callbackQueryId,
        text: action === 'approve' ? 'Approved.' : 'Rejected.'
      })
    })
  }

  // Update Supabase
  const serviceRoleKey =
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? Deno.env.get('SERVICE_ROLE_KEY')
  if (!serviceRoleKey) {
    throw new Error('Missing SERVICE_ROLE_KEY')
  }

  const supabase = createClient(Deno.env.get('SUPABASE_URL')!, serviceRoleKey)

  await supabase
    .from('post_approvals')
    .update({ status: newStatus, updated_at: new Date().toISOString() })
    .eq('post_type', postType)
    .eq('post_date', postDate)

  // Replace buttons with status label
  if (TELEGRAM_API) {
    await fetch(`${TELEGRAM_API}/editMessageReplyMarkup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: chatId,
        message_id: messageId,
        reply_markup: {
          inline_keyboard: [[{ text: label, callback_data: 'done' }]]
        }
      })
    })
  }

  return new Response('ok', { status: 200 })
})
