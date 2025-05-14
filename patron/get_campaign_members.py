"""
Patreon API Documentation for Member Fields

This file documents the Patreon API fields we use in the Patron cog.
Reference: https://docs.patreon.com/

Important Member Fields:
-----------------------

pledge_cadence:
    • Type: Integer
    • Description: Indicates how often the patron is charged.
    • Values:
        - 1: Monthly subscription (default)
        - 12: Yearly subscription
    • Example: A patron with pledge_cadence=12 is billed annually

currently_entitled_amount_cents:
    • Type: Integer
    • Description: The amount (in cents) that the patron is entitled to.
    • Example: 500 means $5.00

last_charge_date:
    • Type: ISO 8601 String
    • Description: The date when the patron was last charged.
    • Used to track processed donations

patron_status:
    • Type: String
    • Description: The status of the patron's membership.
    • Values:
        - "active_patron": Patron with an active, paid membership
        - "declined_patron": Patron whose payment has been declined
        - "former_patron": Was a patron but no longer is
        - "pending_payment": Pending initial payment

Yearly Donation Handling:
------------------------
For yearly subscriptions (pledge_cadence=12), we divide the amount by 12
to get a monthly equivalent for fair reward comparison.

Example:
    $120/year (pledge_cadence=12) -> $10/month for award calculation
""" 