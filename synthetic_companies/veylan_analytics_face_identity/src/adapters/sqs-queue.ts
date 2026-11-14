import { SQSClient, SendMessageCommand, ReceiveMessageCommand, DeleteMessageCommand,
  ChangeMessageVisibilityCommand } from "@aws-sdk/client-sqs";
import type { JobQueue } from "../ports.js";
import { decodeMessage } from "../codec.js";
import { requireThat } from "../errors.js";
import { withDeadline } from "./deadline.js";

export class SqsJobQueue implements JobQueue {
  constructor(private client: SQSClient, private queueUrl: string, private timeoutMs = 5000) {
    requireThat(queueUrl.startsWith("https://") && timeoutMs > 0, "BAD_ADAPTER_CONFIG", "Existing HTTPS queue URL required");
  }
  async send(body: string): Promise<void> {
    decodeMessage(body);
    await withDeadline(this.timeoutMs, signal => this.client.send(new SendMessageCommand({
      QueueUrl: this.queueUrl, MessageBody: body,
    }), { abortSignal: signal }));
  }
  async receive() {
    const response = await withDeadline(this.timeoutMs, signal => this.client.send(new ReceiveMessageCommand({
      QueueUrl: this.queueUrl, MaxNumberOfMessages: 1, WaitTimeSeconds: 1, VisibilityTimeout: 120,
    }), { abortSignal: signal }));
    const message = response.Messages?.[0];
    if (!message) return undefined;
    requireThat(message.ReceiptHandle, "BAD_QUEUE_RESPONSE", "Missing receipt handle");
    // Malformed bodies are explicitly rejected and acknowledged by ExpansionWorker.
    return { receipt: message.ReceiptHandle, body: message.Body ?? "" };
  }
  async ack(receipt: string): Promise<void> {
    await withDeadline(this.timeoutMs, signal => this.client.send(new DeleteMessageCommand({
      QueueUrl: this.queueUrl, ReceiptHandle: receipt,
    }), { abortSignal: signal }));
  }
  async retry(receipt: string, delaySeconds: number): Promise<void> {
    requireThat(Number.isInteger(delaySeconds) && delaySeconds >= 0 && delaySeconds <= 900,
      "BAD_DELAY", "Invalid retry delay");
    await withDeadline(this.timeoutMs, signal => this.client.send(new ChangeMessageVisibilityCommand({
      QueueUrl: this.queueUrl, ReceiptHandle: receipt, VisibilityTimeout: delaySeconds,
    }), { abortSignal: signal }));
  }
}
