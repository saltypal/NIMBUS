// Run through playwright-cli run-code --filename scripts/smoke-ui.js.
// Writes uniquely named synthetic records to the local demo database.
async page => {
  const origin = new URL(page.url()).origin;
  if (!['localhost', '127.0.0.1'].includes(new URL(origin).hostname)) {
    throw new Error('UI smoke must target a local demonstration instance.');
  }
  const health = await (await page.request.get(origin + '/api/health')).json();
  if (!health.demo_mode || health.inference_enabled) {
    throw new Error('Use demo mode with LLM drafting disabled for this manual workflow check.');
  }
  const title = `UI smoke: vibration ${Date.now()}`;
  const textbox = name => page.getByRole('textbox', { name, exact: true });
  const combo = name => page.getByRole('combobox', { name, exact: true });
  const button = name => page.getByRole('button', { name, exact: true });
  async function status(expected) {
    const records = await (await page.request.get(origin + '/api/tickets')).json();
    const ticket = records.find(item => item.title === title);
    if (!ticket || ticket.status !== expected) throw new Error(`Expected ticket status ${expected}`);
    return ticket;
  }
  async function review() {
    await button('Save & review').click();
    await button('Confirm update').waitFor();
  }
  async function accept(expected) {
    await button('Confirm update').click();
    await page.getByRole('status').waitFor();
    return await status(expected);
  }
  await page.request.post(origin + '/api/demo/seed', { data: {} });
  await page.reload();
  await combo('Machine').selectOption('machine_a');
  await textbox('Person ID').fill('ui_smoke_operator');
  await textbox('Reporter name').fill('UI smoke operator');
  await combo('Role').selectOption('operator');
  await button('+ Report a fault').click();
  await textbox('Your note').fill('Unusual vibration after a tool change. Still running. Synthetic note.');
  await textbox('Title *').fill(title);
  await textbox('Symptom *').fill('Unusual vibration');
  await combo('Reported condition *').selectOption('running');
  await textbox('Recent change (optional)').fill('Tool changed');
  await review();
  await accept('open');
  await page.getByRole('button').filter({ has: page.getByRole('heading', { name: title, exact: true }) }).click();

  await combo('Role').selectOption('supervisor');
  await combo('Action').selectOption('record_inspection');
  await textbox('Your note').fill('Checked');
  await textbox('Finding *').fill('Checked');
  await review();
  await button('Confirm update').click();
  await page.getByRole('alert').filter({ hasText: 'Required fields are missing' }).waitFor();
  await status('open');
  await textbox('Check subject *').fill('Tool mount');
  await textbox('Method *').fill('Synthetic visual fixture');
  await textbox('Finding *').fill('Vibration remains; issue unresolved');
  await textbox('Next action *').fill('Monitor and plan corrective work');
  await accept('open');

  await combo('Role').selectOption('operator');
  await combo('Shift').selectOption('night');
  await button('Handover').click();
  await page.getByRole('button', { name: /Read & acknowledge/ }).filter({ hasText: title }).click();
  await textbox('Your note').fill('Read the unresolved fault for the next shift');
  await review();
  await accept('open');
  await button('Board').click();

  await combo('Role').selectOption('supervisor');
  await combo('Action').selectOption('start_work');
  await textbox('Your note').fill('Starting synthetic corrective work');
  await textbox('Work intent *').fill('Synthetic corrective cycle');
  await review();
  await accept('in_progress');
  await combo('Action').selectOption('submit_for_review');
  await textbox('Your note').fill('Synthetic repair finished; request operator verification');
  await textbox('Work summary *').fill('Synthetic repair fixture; no physical machine involved');
  await textbox('Work completed at *').fill(new Date(Date.now() - 60000).toISOString());
  await button('Select demo verification policy').click();
  await review();
  await accept('under_review');

  await combo('Role').selectOption('operator');
  await combo('Action').selectOption('submit_verification');
  await textbox('Your note').fill('Synthetic verification with no vibration under the demo condition');
  await button('Use this ticket’s verification plan').click();
  await textbox('Observed at *').fill(new Date().toISOString());
  await combo('Test result').selectOption('pass');
  await combo('Did the fault occur?').selectOption('no');
  await page.getByRole('spinbutton', { name: 'Completed cycles', exact: true }).fill('4');
  await textbox('Test condition').fill('demo_test_condition');
  await textbox('What did you observe?').fill('Four synthetic cycles without fault');
  await review();
  await button('Confirm update').click();
  await page.getByRole('alert').filter({ hasText: 'required checks have not all passed' }).waitFor();
  await status('under_review');
  await page.getByRole('spinbutton', { name: 'Completed cycles', exact: true }).fill('5');
  await textbox('What did you observe?').fill('Five synthetic cycles without fault');
  await button('Confirm update').click();
  await page.getByRole('status').filter({ hasText: 'ticket closed automatically' }).waitFor();
  const ticket = await status('closed');

  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = await page.evaluate(() => ({ width: innerWidth, content: document.documentElement.scrollWidth }));
  if (mobile.content > mobile.width) throw new Error('Mobile viewport has horizontal overflow.');
  await page.screenshot({ path: 'output/playwright/mobile.png', fullPage: true });

  await button('+ Report a fault').click();
  await combo('Action').selectOption('record_observation');
  await button('Handwriting').click();
  const canvas = page.getByLabel('Handwriting canvas');
  const box = await canvas.boundingBox();
  if (!box) throw new Error('Handwriting canvas is not visible.');
  await canvas.scrollIntoViewIfNeeded();
  const visible = await canvas.boundingBox();
  await page.mouse.move(visible.x + 30, visible.y + 30);
  await page.mouse.down();
  await page.mouse.move(visible.x + 100, visible.y + 65, { steps: 5 });
  await page.mouse.up();
  await page.getByText('Handwriting captured', { exact: true }).waitFor();
  await textbox('Observation *').fill('Synthetic drawing captured; no physical inspection');
  await review();
  await textbox('Review the transcript').fill('Synthetic drawing fixture; manually entered transcript');
  await button('Save text correction').click();
  await button('Confirm update').click();
  await page.getByRole('status').filter({ hasText: 'Recorded. Status: Recorded.' }).waitFor();
  await button('Voice').click();
  await button('Record voice note').waitFor();
  await page.getByLabel('Upload audio').waitFor();
  // Real microphone permission/hardware and transcription quality are separate checks.
  await button('Text').click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: 'output/playwright/desktop.png', fullPage: true });
  return {
    report: true, incomplete_inspection_rejected: true, acknowledgment_kept_open: true,
    insufficient_verification_rejected: true, corrected_evidence_closed: true,
    handwriting_capture_manual_fallback: true, voice_controls_available: true,
    mobile, ticket_id: ticket._id, events: ticket.activities.length,
    model_quality_tested: false,
  };
}
