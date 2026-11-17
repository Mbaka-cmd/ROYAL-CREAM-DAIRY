# ADDITIONAL REQUIREMENTS (read first, these override anything below that conflicts)

- Environment: venv activation is blocked on this machine. Run commands with .\.venv\Scripts\python.exe (or system python if that fails), e.g.
  $env:DJANGO_SETTINGS_MODULE="config.settings.development"; python manage.py test tests
- Repo hygiene: do not read, modify or commit .env, db.sqlite3, _backup_* items, *_dump.txt or audit*.txt. The branch feature/whatsapp-receipts already exists and db.sqlite3 has been backed up.
- There is no existing "preparing" notification type. Propose adding one in the plan, with its migration impact.
- If no authorized "record cash collected" action exists, propose the smallest addition: owner-only, POST, CSRF-protected, records who and when, creates an audit entry, sets payment state through the existing payment architecture.
- OPENED_MANUALLY means "the owner clicked Send via WhatsApp". It is never evidence of sending or delivery.
- The preview text and the wa.me message must come from the same builder call. Add a test that the URL-decoded wa.me text equals the preview text.
- Idempotency must be enforced at database level (unique constraint or equivalent on order + message type), not just in Python. State what database production uses and whether the constraint works there.
- Confirm OrderItem stores name, unit price and line total as snapshots. If it reads live product prices, report it as a risk.
- The /order/<token>/ page must never show the customer's phone number or any owner notes. Add a test.
- Migrations must be additive and reversible, with defaults for existing rows.

---

# ROYAL CREAM DAIRY - ENGINEERING IMPLEMENTATION CONTRACT
## Phase 1: Dynamic WhatsApp Receipts, Order Notifications & Delivery Tracking

Act as a senior Django engineer working on the EXISTING Royal Cream Dairy application.

Your assignment is to extend the existing application with a reliable order communication and fulfilment workflow.

This is an existing production-oriented project, NOT a greenfield application.

Your first responsibility is to inspect and understand the existing architecture. Your second responsibility is to propose an implementation plan. You MUST WAIT FOR MY EXPLICIT APPROVAL BEFORE MODIFYING ANY FILE.

---

# 1. VERIFIED PROJECT FACTS - VERIFY AGAINST CODE

The following are project facts supplied by the project owner. Inspect the repository and verify each before relying on it.

| Area | Expected configuration |
|---|---|
| Operating system | Windows development environment |
| Python | 3.12 |
| Django | 5.2 |
| Settings module | config.settings.development |
| Local database | SQLite |
| Production hosting | cPanel-style Passenger |
| WSGI entry point | passenger_wsgi.py |
| Tracking page | Existing /order/<token>/ |
| Notifications | Existing notifications app with queued notification records |
| Final order status | COMPLETED |
| Background infrastructure | No Docker, Celery or Redis |

Do not introduce Docker, Celery or Redis.

Do not create a replacement tracking system.

Do not create a /track/ endpoint.

Do not rename existing order statuses.

Use COMPLETED as the final delivery status.

Use a configurable public site URL setting when constructing absolute links.

Never hardcode the production domain.

If the actual code contradicts any supplied fact, report the discrepancy before proceeding.

---

# 2. MANDATORY PROCESS - TWO DISTINCT PHASES

## PHASE A: READ-ONLY AUDIT

Do not edit, create, delete, migrate or reformat any project files during this phase.

Inspect:

1. Project directory structure.
2. Django settings and environment configuration.
3. Order models and order item models.
4. Existing order status definitions and transitions.
5. Existing checkout workflow.
6. Existing customer order completion page.
7. Existing /order/<token>/ tracking view, URL and template.
8. Existing notification models and queueing logic.
9. Existing notification templates or message builders.
10. Existing WhatsApp links or phone formatting utilities.
11. Existing payment models, callbacks and payment verification.
12. Existing stock deduction and order completion logic.
13. Existing owner dashboard and order detail templates.
14. Existing tests and test configuration.
15. Passenger WSGI configuration and production deployment settings.

Identify reusable components and potential conflicts.

Do not assume a model or method exists merely because it is described in this brief.

## 3. BASELINE TESTING

Before modifying anything:

Run the existing test suite using the project's actual configuration.

Expected local configuration:

DJANGO_SETTINGS_MODULE=config.settings.development

Use the appropriate existing test command.

Report:

- Command executed.
- Number of tests discovered.
- Number passed.
- Number failed.
- Number skipped.
- Any environment-related errors.
- Any existing failures unrelated to this task.

Do not change code to make the baseline pass.

Do not conceal existing failures.

If tests cannot run, explain the exact blocker.

## 4. STOP AND REQUEST APPROVAL

After the audit and baseline tests, provide:

### A. Architecture findings
What actually exists in the repository.

### B. Existing reusable components
Models, views, services, templates, utilities and notification infrastructure.

### C. Proposed implementation
Exact files to modify and any new files required.

### D. Database impact
Any necessary fields, migrations or changes to existing notification records.

### E. Test plan
Specific tests to add or update.

### F. Risks
Potential impact on checkout, payment verification, inventory and Passenger deployment.

Then STOP.

Do not edit any files until I explicitly approve the proposed plan.

---

# 5. PHASE B - IMPLEMENTATION AFTER APPROVAL

Implement only the approved changes.

Work in small, reviewable steps.

After EACH implementation step:

1. Run the relevant tests.
2. Report the results.
3. Inspect the changes.
4. Correct regressions before moving forward.

Run the complete existing test suite after integration.

Do not silently continue past failing tests.

---

# 6. REQUIRED FUNCTIONALITY

## A. ORDER RECEIVED

When checkout successfully creates an order:

Reuse the existing notification infrastructure.

Generate the existing notification types where appropriate:

- Order received (customer).
- New order (owner).

The customer acknowledgement should communicate:

"Hello {customer_name},

Thank you for choosing Royal Cream Dairy!

We have received your order {order_number}.

Our team is reviewing your order and will update you once it has been confirmed.

You can follow your order here:
{absolute_tracking_url}

Pure Goodness, Every Day."

All values must be populated from the actual order.

Do not claim the order has been confirmed at this stage.

Use the existing /order/<token>/ URL.

Build the absolute URL from a configurable public site URL setting.

## B. ORDER CONFIRMED - DYNAMIC RECEIPT

When the owner confirms an order, generate a dynamic receipt.

Example presentation:

ROYAL CREAM DAIRY
ORDER CONFIRMATION RECEIPT

Order: {order_number}
Date: {order_date}

Customer: {customer_name}
Phone: {customer_phone}
Delivery: {delivery_location}

ITEMS

{product_name} x {quantity} - KSh {line_total}

Subtotal: KSh {subtotal}
Delivery: KSh {delivery_fee}
Discount: KSh {discount_if_applicable}
TOTAL: KSh {total}

Payment Method: {payment_method}
Payment Status: {payment_status}

Order Status: CONFIRMED

Track your order:
{absolute_tracking_url}

Thank you for choosing Royal Cream Dairy.

IMPORTANT:

- Use existing order calculations.
- Never duplicate pricing calculations.
- Do not hardcode customer or product details.
- Preserve the existing currency representation.
- Handle discounts and delivery fees according to actual model capabilities.
- Do not invent fields.

## C. WHATSAPP CLICK-TO-CHAT

PHASE 1 ONLY.

Use WhatsApp click-to-chat via wa.me.

Do not implement the WhatsApp Business Cloud API sender.

Do not introduce external messaging SDKs.

Implement a reusable sender abstraction so a real API sender can be introduced later without rewriting message generation.

Expected behaviour:

1. Owner opens order details.
2. Owner sees a generated receipt.
3. Owner previews the complete message.
4. Owner clicks SEND VIA WHATSAPP.
5. Browser opens WhatsApp using the customer's normalized phone number.
6. Message is pre-populated.
7. Owner manually presses Send in WhatsApp.

Construct properly URL-encoded messages.

Normalize Kenyan numbers safely.

For example:

0748077609 -> 254748077609

Validate the number before generating the URL.

Never expose API credentials.

### CRITICAL MESSAGE STATUS SEMANTICS

The notification infrastructure must distinguish:

QUEUED
OPENED_MANUALLY
SENT

Interpretation:

QUEUED:
The notification has been generated and queued by the application.

OPENED_MANUALLY:
The owner opened WhatsApp with the pre-populated message.

SENT:
Only use when a genuine sending mechanism provides reliable evidence that the message was sent.

Opening a wa.me link MUST NEVER mark a notification SENT.

Do not use DELIVERED as a WhatsApp message status.

Do not claim WhatsApp delivery or read confirmation.

Inspect existing notification status choices before changing anything.

Preserve backward compatibility with existing records and notification processing.

If a status migration is necessary, propose it and explain its impact before implementing it.

## D. OWNER ORDER DETAIL PAGE

Extend the existing owner order detail page.

When an order is CONFIRMED, display a communication panel:

CUSTOMER COMMUNICATION

- Customer phone.
- Order reference.
- Payment status.
- Current order status.
- Generated receipt preview.

Actions:

[Preview Receipt]
[Send via WhatsApp]
[Copy Receipt]

The receipt must be generated from the current persisted order.

Do not create separate hardcoded templates for individual customers.

Record OPENED_MANUALLY only when the application can reliably establish that the WhatsApp launch action was initiated.

Do not treat a successful browser redirect or URL construction as proof that the customer received the message.

## E. PREPARING STATUS

When the owner transitions the order to PREPARING:

Generate the appropriate existing notification.

Message:

"Hello {customer_name},

Your Royal Cream Dairy order {order_number} is now being prepared.

We are getting your dairy products ready.

Order Total: KSh {total}

Track your order:
{tracking_url}"

Provide the appropriate owner communication action.

Prevent duplicate notification generation for repeated transitions.

## F. OUT FOR DELIVERY

When the owner transitions the order to OUT_FOR_DELIVERY:

Generate a dynamic delivery notification.

Message:

"Good news, {customer_name}!

Your Royal Cream Dairy order {order_number} is now OUT FOR DELIVERY.

Your order:

{dynamic_items}

Total: KSh {total}

Payment Method: {payment_method}
Payment Status: {payment_status}

Delivery Location: {delivery_location}

Track your order:
{tracking_url}

Thank you for choosing Royal Cream Dairy!"

Reuse the existing Out for delivery notification type.

Provide preview and WhatsApp actions.

## G. COMPLETED - FINAL DELIVERY RECEIPT

Use the application's existing COMPLETED status.

Do not introduce DELIVERED as a new order status.

When the owner marks the order COMPLETED:

- Record the completion timestamp if the existing model supports it or an approved field is added.
- Record the responsible staff account where supported.
- Update the existing tracking page.
- Generate the final completion receipt.
- Generate/reuse the existing Order completed notification.
- Provide a WhatsApp preview and send action.

Example:

ROYAL CREAM DAIRY
DELIVERY COMPLETION RECEIPT

Order: {order_number}

Customer: {customer_name}

{dynamic_items}

Subtotal: KSh {subtotal}
Delivery: KSh {delivery_fee}
TOTAL: KSh {total}

Payment Method: {payment_method}
Payment Status: {payment_status}

Delivery Status: COMPLETED

Completed: {completion_timestamp}

Thank you for choosing Royal Cream Dairy.

Pure Goodness, Every Day.

The receipt must accurately reflect the payment status at the time it is generated.

---

# 7. PAYMENT INTEGRITY

Payment status and delivery status are independent.

Examples:

PAY ON DELIVERY:
- Before collection: UNPAID.
- After verified collection: PAID.

MPESA:
- Before verified callback: PENDING.
- After verified successful callback: PAID.

Do not infer successful payment from delivery completion.

Do not allow a frontend action to arbitrarily mark an order paid.

Reuse the existing payment transaction records and verified callback implementation.

If a receipt is regenerated, it must use the authoritative current payment state.

---

# 8. EXISTING CUSTOMER TRACKING PAGE

Extend the existing:

/order/<token>/

Do not create another tracking URL or token system.

Enhance its existing interface to display:

- Order reference.
- Customer order summary.
- Products and quantities.
- Subtotal.
- Delivery fee.
- Total.
- Payment method.
- Payment status.
- Current order status.
- Status history.
- Completion information where applicable.

Expected timeline:

1. Order received.
2. Confirmed.
3. Preparing.
4. Out for delivery.
5. Completed.

Use actual persisted status history where available.

Do not display a future status as completed.

Ensure the existing tracking token remains secure.

Do not expose unrelated customer or owner information.

---

# 9. EXISTING ORDER COMPLETION PAGE

Extend the existing checkout success page.

After a successful order submission display:

"Your order has been received!"

Show:

- Order reference.
- Product summary.
- Quantities.
- Total.
- Delivery fee.
- Payment method.
- Payment status.
- Delivery location.
- Existing tracking link.

Buttons:

[Track My Order]
[Contact Royal Cream Dairy on WhatsApp]

Clearly distinguish RECEIVED from CONFIRMED.

Do not imply that the owner has confirmed an order before the actual status transition.

---

# 10. ARCHITECTURE AND CODE QUALITY

Follow the project's existing architecture.

Prefer a small reusable service layer.

Possible responsibilities, subject to the audit:

Receipt/message builder:
- Build order received message.
- Build confirmation receipt.
- Build preparation notification.
- Build out-for-delivery notification.
- Build completion receipt.

WhatsApp link builder:
- Normalize phone numbers.
- Validate numbers.
- Encode messages.
- Build wa.me URLs.

Notification integration:
- Reuse existing notification model.
- Reuse existing notification queue.
- Prevent duplicate notifications.
- Preserve retry and error tracking.

Do not create unnecessary apps, models, abstractions or infrastructure.

Keep message construction independent of the transport mechanism.

A future API sender should be replaceable without rewriting the receipt templates.

---

# 11. SECURITY AND RELIABILITY

Verify:

- Owner authorization.
- CSRF protection.
- Secure tracking access.
- Phone number validation.
- Safe URL encoding.
- Server-side order calculations.
- Payment integrity.
- Idempotent notification generation.
- No duplicate notifications on repeated transitions.
- Correct transaction boundaries.
- No external network calls inside long database transactions.

Respect SQLite development and the actual production database configuration.

Do not assume the production database is SQLite.

---

# 12. TESTING

Add tests for:

1. Dynamic receipt content.
2. Correct item quantities and totals.
3. Delivery fee handling.
4. Payment status accuracy.
5. Order received notification.
6. Order confirmation notification.
7. Preparation notification.
8. Out-for-delivery notification.
9. Completion notification.
10. Kenyan phone normalization.
11. WhatsApp URL encoding.
12. QUEUED status.
13. OPENED_MANUALLY status.
14. SENT status semantics.
15. No false SENT status after opening WhatsApp.
16. Duplicate notification prevention.
17. Existing tracking token behaviour.
18. Tracking page status updates.
19. Unauthorized owner actions.
20. Existing payment callback integrity.
21. Existing checkout workflow.
22. Existing stock workflow.

Run tests after every implementation step.

Do not delete existing tests or weaken assertions.

---

# 13. DEPLOYMENT COMPATIBILITY

Production uses cPanel-style Passenger and passenger_wsgi.py.

Ensure:

- No Docker requirements.
- No Redis requirements.
- No Celery requirements.
- No background worker assumptions.
- No incompatible development-only dependencies.
- Migrations are compatible with the actual production database.
- Public URL configuration is environment-driven.
- Static assets continue working.
- Existing Passenger startup remains functional.

Document the deployment steps and any environment variables required.

---

# 14. FINAL ACCEPTANCE CRITERIA

The feature is complete only when:

1. Customer checkout creates an order using the existing workflow.
2. Existing notifications infrastructure generates the appropriate messages.
3. Owner can confirm an order.
4. Application generates an accurate dynamic receipt.
5. Owner previews the receipt.
6. Owner opens WhatsApp with a pre-populated message.
7. Application records OPENED_MANUALLY, not SENT.
8. Customer can use the existing /order/<token>/ page.
9. Customer can see preparation and delivery progress.
10. Owner can transition the order to OUT_FOR_DELIVERY.
11. Owner can transition the order to COMPLETED.
12. A final delivery receipt is generated.
13. Payment status remains accurate.
14. No duplicate notification records are created through repeated transitions.
15. Existing checkout, stock, payment and tracking functionality remains intact.

# FINAL INSTRUCTION

START WITH PHASE A ONLY.

AUDIT THE CODE.

RUN THE BASELINE TESTS.

PRESENT THE FINDINGS AND IMPLEMENTATION PLAN.

STOP AND WAIT FOR MY EXPLICIT APPROVAL.

DO NOT MODIFY ANY FILES BEFORE APPROVAL.