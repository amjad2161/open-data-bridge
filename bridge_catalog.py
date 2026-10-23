"""Windsor-style connector catalog and deterministic local query engine.

This module is intentionally provider-neutral.  It models the public contract
that a real adapter must satisfy, while the local build only executes the
synthetic connectors.  No provider endpoint, credential, or private Windsor
implementation is copied here.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


class ContractError(ValueError):
    """A user-visible, fail-closed query or capability error."""


COMMON_FIELDS: dict[str, dict[str, str]] = {
    "date": {"type": "DATE", "role": "dimension", "description": "Reporting date"},
    "source": {"type": "TEXT", "role": "dimension", "description": "Source channel"},
    "account_id": {"type": "TEXT", "role": "dimension", "description": "Provider account identifier"},
    "account_name": {"type": "TEXT", "role": "dimension", "description": "Provider account name"},
    "campaign": {"type": "TEXT", "role": "dimension", "description": "Campaign name"},
    "spend": {"type": "NUMERIC", "role": "metric", "description": "Spend in the source currency"},
    "impressions": {"type": "NUMERIC", "role": "metric", "description": "Impressions"},
    "clicks": {"type": "NUMERIC", "role": "metric", "description": "Clicks"},
    "reach": {"type": "NUMERIC", "role": "metric", "description": "Unique reach"},
    "conversions": {"type": "NUMERIC", "role": "metric", "description": "Conversions"},
    "revenue": {"type": "NUMERIC", "role": "metric", "description": "Attributed revenue"},
    "ctr": {"type": "NUMERIC", "role": "metric", "description": "Click-through rate, percent"},
    "cpc": {"type": "NUMERIC", "role": "metric", "description": "Cost per click"},
    "cpa": {"type": "NUMERIC", "role": "metric", "description": "Cost per conversion"},
    "roas": {"type": "NUMERIC", "role": "metric", "description": "Return on ad spend"},
    "currency": {"type": "TEXT", "role": "dimension", "description": "ISO-like source currency code"},
}


# Synced from the public Windsor MCP datasource directory on 2026-10-23.
# These IDs are catalog metadata only in this local bridge.  They are not
# credentials, adapters, or evidence that an account is connected.
WINDSOR_DATASOURCE_URL = "https://mcp-beta.windsor.ai/datasources"
WINDSOR_CONNECTOR_IDS = tuple(
    dict.fromkeys(
        """
        activecampaign adalyser adform adjust adobe adobe2 adroll adtraction aha
        ahrefs aircall airtable all alpha_vantage amazon_ads amazon_dsp amazon_s3
        amazon_sp amazon_sqs amazon_vendor amplitude apify_dataset appfollow
        apple_search_ads applovin appnexus appsflyer apsis_one ashby attentive auth0
        awin aws_cloudtrail azure_table babelforce bamboo_hr basis_dsp big_query
        bigcommerce bing bing_webmaster bling boxcast braintree branch brandfolder
        braze breezometer callrail captain_data cart chargebee chargify chartmogul
        cj clickmagick clickup_api clockify close_com cm360 coda coin_api
        coinmarketcap commercetools commissionfactory configcat confluence connectif
        contractors_cloud convertkit convex copper courier criteo currency_conversion
        customer_io daisycon datadog datamediq datascope delighted digistorm dixa
        dockerhub dragonmetrics dremio drift dv360 dynamics365 ebay emailoctopus
        everflow everhour exchange_rates exoclick facebook facebook_leads
        facebook_organic faker fastbill fauna file firebolt firstpromoter flashtalking
        flexport freshcaller freshdesk freshsales freshservice fullstory gainsight_px
        gemius genesys getlago github gitlab glassfrog gmailcsv gnews gocardless
        gohighlevel gong google_ad_manager google_ads google_merchant google_my_business
        google_pagespeed google_search_ads google_webfonts google_workspace_admin_reports
        googleanalytics googleanalytics4 googlesheets gravity_forms greenhouse gridly
        harness harvest hawk_dsp hellobaton hubplanner hubspot idealo impact incomeaccess
        insightly instagram instagram_public instatus intercom intruder ip2whois iterable
        jira k6cloud klarna klaus_api klaviyo kommo kustomer_singer kyriba kyve
        launchdarkly lazada leadinfo lemlist lever_hiring line line_ads lineleader
        linkedin linkedin_organic linnworks lokalise looker magento mailchimp mailerlite
        mailersend mailgun mailjet_mail mailjet_sms matomo mediago merge metabase
        metricool microsoft_clarity microsoft_dataverse microsoft_teams mixpanel mntn
        monday mongodb my_hours mysql n8n nasa netsuite news_api nextdoor notion nytimes
        okta omnisend onesignal openai_ads openweather opsgenie orb orbit oura outbrain
        outreach pagerduty pardot partnerize partnerstack paypal_transaction paystack
        pendo persistiq pexels_api pinterest pinterest_organic pipedrive pivotal_tracker
        piwik_pro plaid plausible pocket pokeapi polygon_stock_api postgresql posthog
        prestashop primetric productive profitwell punk_api pypi qonto qualaroo
        quickbooks quora railz rakuten_advertising rd_station_marketing readpeak recharge
        recreation recruitee recurly reddit redshift reply_io retently rki_covid rocket_chat
        rss rtbhouse salesforce salesforce_marketing salesloft sap_fieldglass search_metrics
        searchconsole secoda semrush sendgrid sendinblue senseforce sentry seranking
        serpstat sftp sftp_bulk shiphero shopee shopee_ads shopify shortio similarweb
        simplifi slack smaily smartengage smartsheets snapchat snowflake sonar_cloud spotify
        sproutsocial square stackadapt statuspage strava stripe supabase survey_sparrow
        surveycto surveymonkey sweet_tv taboola teads tempo the_guardian_api threads ticimax
        tiktok tiktok_organic tiktok_shop timely tmdb todoist toggl tradedesk tradedoubler
        trafficjunky trello triplewhale trustpilot tvmaze_schedule twilio twilio_taskrouter
        twinred twitter typeform unleash us_census vantage vibe visma_economic vistar vitally
        waiteraid walmart weatherstack webflow whatconverts wikipedia_pageviews woocommerce
        wordpress workable workramp wrike x_organic xero yahoo_finance_price yahoo_japan
        yandex_metrica yotpo yougov_brandindex younium youtube zapier_supported_storage
        zendesk_chat zendesk_sell zendesk_sunshine zendesk_support zendesk_talk zenefits
        zenloop zoho zoom zuora
        """.split()
    )
)


DEMO_FIELDS = {
    key: COMMON_FIELDS[key]
    for key in (
        "date",
        "source",
        "account_id",
        "account_name",
        "campaign",
        "spend",
        "conversions",
        "currency",
    )
}
DEMO_FIELDS.update({key: COMMON_FIELDS[key] for key in ("ctr", "cpc", "cpa", "roas")})

BLENDED_FIELDS = {
    key: COMMON_FIELDS[key]
    for key in COMMON_FIELDS
}


DEMO_ROWS: list[dict[str, Any]] = [
    {
        "date": "2026-01-01",
        "source": "demo_ads",
        "account_id": "demo-account-1",
        "account_name": "Synthetic Demo Account",
        "campaign": "Example A",
        "spend": 120.0,
        "conversions": 8,
        "currency": "USD",
    },
    {
        "date": "2026-01-02",
        "source": "demo_ads",
        "account_id": "demo-account-1",
        "account_name": "Synthetic Demo Account",
        "campaign": "Example A",
        "spend": 95.0,
        "conversions": 7,
        "currency": "USD",
    },
    {
        "date": "2026-01-01",
        "source": "demo_ads",
        "account_id": "demo-account-1",
        "account_name": "Synthetic Demo Account",
        "campaign": "Example B",
        "spend": 80.0,
        "conversions": 2,
        "currency": "USD",
    },
]


BLENDED_ROWS: list[dict[str, Any]] = [
    {
        "date": "2026-01-01",
        "source": "meta_ads",
        "account_id": "meta-demo-1",
        "account_name": "Synthetic Meta Business",
        "campaign": "Example A",
        "spend": 120.0,
        "impressions": 5200,
        "clicks": 210,
        "reach": 4300,
        "conversions": 8,
        "revenue": 640.0,
        "currency": "USD",
    },
    {
        "date": "2026-01-02",
        "source": "meta_ads",
        "account_id": "meta-demo-1",
        "account_name": "Synthetic Meta Business",
        "campaign": "Example A",
        "spend": 95.0,
        "impressions": 4100,
        "clicks": 164,
        "reach": 3500,
        "conversions": 7,
        "revenue": 560.0,
        "currency": "USD",
    },
    {
        "date": "2026-01-01",
        "source": "google_ads",
        "account_id": "google-demo-1",
        "account_name": "Synthetic Google Ads Account",
        "campaign": "Example B",
        "spend": 80.0,
        "impressions": 3800,
        "clicks": 121,
        "reach": 3000,
        "conversions": 2,
        "revenue": 180.0,
        "currency": "USD",
    },
    {
        "date": "2026-01-02",
        "source": "linkedin_ads",
        "account_id": "linkedin-demo-1",
        "account_name": "Synthetic LinkedIn Account",
        "campaign": "Example C",
        "spend": 70.0,
        "impressions": 2200,
        "clicks": 48,
        "reach": 1900,
        "conversions": 3,
        "revenue": 240.0,
        "currency": "USD",
    },
]


@dataclass(frozen=True)
class ConnectorSpec:
    connector_id: str
    name: str
    category: str
    auth: str
    implementation_status: str
    read_supported: bool
    write_supported: bool
    fields: dict[str, dict[str, str]]
    rows: list[dict[str, Any]]
    connected_accounts: list[dict[str, str]]
    scopes: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    custom_fields: tuple[dict[str, str], ...] = ()
    docs_url: str = ""
    catalog_origin: str = "bridge"


ACTION_SCHEMAS: dict[str, tuple[dict[str, Any], ...]] = {
    "facebook": (
        {"id": "create_campaign", "name": "Create campaign", "description": "Create a paused Meta campaign", "schema": {"type": "object", "properties": {"name": {"type": "string"}, "objective": {"type": "string"}}, "required": ["name"]}},
        {"id": "pause_campaign", "name": "Pause campaign", "description": "Pause a Meta campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "enable_campaign", "name": "Enable campaign", "description": "Enable a Meta campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "set_budget", "name": "Set budget", "description": "Set a Meta campaign or ad set budget", "schema": {"type": "object", "properties": {"entity_id": {"type": "string"}, "amount": {"type": "number"}, "period": {"type": "string"}}, "required": ["entity_id", "amount"]}},
        {"id": "boost_post", "name": "Boost post", "description": "Boost an existing Facebook post", "schema": {"type": "object", "properties": {"post_id": {"type": "string"}, "budget": {"type": "number"}}, "required": ["post_id", "budget"]}},
    ),
    "meta_ads": (
        {"id": "create_campaign", "name": "Create campaign", "description": "Create a paused Meta campaign", "schema": {"type": "object", "properties": {"name": {"type": "string"}, "objective": {"type": "string"}}, "required": ["name"]}},
        {"id": "pause_campaign", "name": "Pause campaign", "description": "Pause a Meta campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "enable_campaign", "name": "Enable campaign", "description": "Enable a Meta campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "set_budget", "name": "Set budget", "description": "Set a Meta campaign or ad set budget", "schema": {"type": "object", "properties": {"entity_id": {"type": "string"}, "amount": {"type": "number"}, "period": {"type": "string"}}, "required": ["entity_id", "amount"]}},
    ),
    "google_ads": (
        {"id": "create_campaign", "name": "Create campaign", "description": "Create a paused Google Ads campaign", "schema": {"type": "object", "properties": {"name": {"type": "string"}, "budget_amount_micros": {"type": "integer"}, "channel_type": {"type": "string"}}, "required": ["name", "budget_amount_micros"]}},
        {"id": "pause_campaign", "name": "Pause campaign", "description": "Pause a Google Ads campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "enable_campaign", "name": "Enable campaign", "description": "Enable a Google Ads campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "set_bidding", "name": "Set bidding", "description": "Change a Google Ads bidding strategy", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}, "strategy": {"type": "string"}, "target_cpa": {"type": "number"}}, "required": ["campaign_id", "strategy"]}},
        {"id": "manage_keywords", "name": "Manage keywords", "description": "Add, update or remove Google Ads keywords", "schema": {"type": "object", "properties": {"ad_group_id": {"type": "string"}, "operation": {"type": "string"}, "keywords": {"type": "array", "items": {"type": "string"}}}, "required": ["ad_group_id", "operation", "keywords"]}},
    ),
    "tiktok": (
        {"id": "pause_campaign", "name": "Pause campaign", "description": "Pause a TikTok campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "enable_campaign", "name": "Enable campaign", "description": "Enable a TikTok campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "set_budget", "name": "Set budget", "description": "Set a TikTok campaign budget", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}, "amount": {"type": "number"}}, "required": ["campaign_id", "amount"]}},
    ),
    "linkedin": (
        {"id": "pause_campaign", "name": "Pause campaign", "description": "Pause a LinkedIn campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "enable_campaign", "name": "Enable campaign", "description": "Enable a LinkedIn campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "set_budget", "name": "Set budget", "description": "Set a LinkedIn campaign budget", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}, "amount": {"type": "number"}}, "required": ["campaign_id", "amount"]}},
    ),
    "bing": (
        {"id": "pause_campaign", "name": "Pause campaign", "description": "Pause a Microsoft Advertising campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "enable_campaign", "name": "Enable campaign", "description": "Enable a Microsoft Advertising campaign", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]}},
        {"id": "set_budget", "name": "Set budget", "description": "Set a Microsoft Advertising budget", "schema": {"type": "object", "properties": {"campaign_id": {"type": "string"}, "amount": {"type": "number"}}, "required": ["campaign_id", "amount"]}},
    ),
    "instagram": (
        {"id": "create_image_post", "name": "Create image post", "description": "Create an Instagram image post", "schema": {"type": "object", "properties": {"image_url": {"type": "string", "format": "uri"}, "caption": {"type": "string"}}, "required": ["image_url"]}},
        {"id": "comment_on_post", "name": "Comment on post", "description": "Add a comment to an Instagram post", "schema": {"type": "object", "properties": {"media_id": {"type": "string"}, "message": {"type": "string"}}, "required": ["media_id", "message"]}},
    ),
    "google_my_business": (
        {"id": "create_post", "name": "Create local post", "description": "Create a Google Business Profile post", "schema": {"type": "object", "properties": {"location_id": {"type": "string"}, "summary": {"type": "string"}}, "required": ["location_id", "summary"]}},
        {"id": "reply_review", "name": "Reply to review", "description": "Reply to a Google Business Profile review", "schema": {"type": "object", "properties": {"review_id": {"type": "string"}, "comment": {"type": "string"}}, "required": ["review_id", "comment"]}},
    ),
    "klaviyo": (
        {"id": "create_flow", "name": "Create flow", "description": "Create a Klaviyo flow", "schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        {"id": "set_flow_status", "name": "Set flow status", "description": "Change a Klaviyo flow status", "schema": {"type": "object", "properties": {"flow_id": {"type": "string"}, "status": {"type": "string"}}, "required": ["flow_id", "status"]}},
    ),
    "amazon_sp": (
        {"id": "update_listing", "name": "Update listing", "description": "Update an Amazon Seller Central product listing", "schema": {"type": "object", "properties": {"sku": {"type": "string"}, "changes": {"type": "object"}}, "required": ["sku", "changes"]}},
    ),
}


def _specs() -> dict[str, ConnectorSpec]:
    common_accounts = [
        {"id": "demo-account-1", "name": "Synthetic Demo Account", "provider": "demo_ads"}
    ]
    blended_accounts = [
        {"id": "meta-demo-1", "name": "Synthetic Meta Business", "provider": "meta_ads"},
        {"id": "google-demo-1", "name": "Synthetic Google Ads Account", "provider": "google_ads"},
        {"id": "linkedin-demo-1", "name": "Synthetic LinkedIn Account", "provider": "linkedin_ads"},
    ]
    common_custom = (
        {"id": "ctr", "name": "Click-through rate", "expression": "clicks / impressions * 100"},
        {"id": "cpc", "name": "Cost per click", "expression": "spend / clicks"},
        {"id": "cpa", "name": "Cost per conversion", "expression": "spend / conversions"},
        {"id": "roas", "name": "Return on ad spend", "expression": "revenue / spend"},
    )
    result: dict[str, ConnectorSpec] = {
        "demo_ads": ConnectorSpec(
            "demo_ads",
            "Synthetic Ads Demo",
            "demo",
            "none",
            "implemented",
            True,
            False,
            DEMO_FIELDS,
            DEMO_ROWS,
            common_accounts,
            custom_fields=common_custom,
        ),
        "all": ConnectorSpec(
            "all",
            "Blended marketing data",
            "blended",
            "mixed",
            "implemented",
            True,
            False,
            BLENDED_FIELDS,
            BLENDED_ROWS,
            blended_accounts,
            custom_fields=common_custom,
            docs_url="https://windsor.ai/data-field/all/",
        ),
    }
    planned = [
        ("meta_ads", "Meta Ads", "advertising", "meta", ("ads_read", "business_management")),
        ("facebook_pages", "Facebook Pages", "social", "meta", ("pages_read_engagement", "pages_manage_posts")),
        ("instagram_business", "Instagram Business", "social", "meta", ("instagram_basic", "instagram_content_publish")),
        ("google_ads", "Google Ads", "advertising", "oauth2", ("https://www.googleapis.com/auth/adwords",)),
        ("google_analytics_4", "Google Analytics 4", "analytics", "oauth2", ("https://www.googleapis.com/auth/analytics.readonly",)),
        ("linkedin_ads", "LinkedIn Ads", "advertising", "oauth2", ("r_ads_reporting",)),
        ("linkedin_pages", "LinkedIn Pages", "social", "oauth2", ("rw_organization_admin",)),
        ("tiktok_ads", "TikTok Ads", "advertising", "oauth2", ("reporting",)),
        ("youtube", "YouTube", "social", "oauth2", ("https://www.googleapis.com/auth/youtube.readonly",)),
        ("shopify", "Shopify", "commerce", "oauth2", ("read_orders", "read_products")),
        ("hubspot", "HubSpot", "crm", "oauth2", ("crm.objects.contacts.read",)),
        ("klaviyo", "Klaviyo", "marketing", "api_key_or_oauth", ("campaigns:read",)),
        ("mailchimp", "Mailchimp", "marketing", "oauth2", ("reports.read",)),
        ("pinterest_ads", "Pinterest Ads", "advertising", "oauth2", ("ads:read",)),
        ("snapchat_ads", "Snapchat Ads", "advertising", "oauth2", ("snapchat.ads.read",)),
        ("bing_ads", "Microsoft Advertising", "advertising", "oauth2", ("ads.read",)),
        ("woocommerce", "WooCommerce", "commerce", "api_key", ("read",)),
    ]
    for connector_id, name, category, auth, scopes in planned:
        result[connector_id] = ConnectorSpec(
            connector_id,
            name,
            category,
            auth,
            "catalog_only",
            False,
            False,
            COMMON_FIELDS,
            [],
            [],
            scopes=scopes,
            writes=("not_implemented",),
            custom_fields=common_custom,
        )
    for connector_id in WINDSOR_CONNECTOR_IDS:
        if connector_id in result:
            continue
        result[connector_id] = ConnectorSpec(
            connector_id=connector_id,
            name=connector_id.replace("_", " ").title(),
            category="catalog",
            auth="oauth2_or_manual",
            implementation_status="catalog_only",
            read_supported=False,
            write_supported=False,
            fields=COMMON_FIELDS,
            rows=[],
            connected_accounts=[],
            scopes=(),
            writes=("not_implemented",),
            custom_fields=common_custom,
            docs_url="https://mcp-beta.windsor.ai/",
            catalog_origin="windsor_live_catalog",
        )
    return result


CATALOG: dict[str, ConnectorSpec] = _specs()
ACTIVE_CONNECTORS = ("demo_ads", "all")


def _serialize_spec(spec: ConnectorSpec) -> dict[str, Any]:
    return {
        "id": spec.connector_id,
        "name": spec.name,
        "category": spec.category,
        "auth": spec.auth,
        "implementation_status": spec.implementation_status,
        "available": spec.read_supported,
        "read_supported": spec.read_supported,
        "write_supported": spec.write_supported,
        "connected_accounts": spec.connected_accounts,
        "required_scopes": list(spec.scopes),
        "writes": list(spec.writes),
        "actions": [item["id"] for item in ACTION_SCHEMAS.get(spec.connector_id, ())],
        "options": ["date_preset", "date_from", "date_to", "select_accounts", "filters", "breakdowns"],
        "catalog_origin": spec.catalog_origin,
        "docs_url": spec.docs_url or None,
    }


def list_connectors(include_not_yet_connected: bool = False) -> list[dict[str, Any]]:
    ids = list(CATALOG) if include_not_yet_connected else list(ACTIVE_CONNECTORS)
    return [_serialize_spec(CATALOG[connector_id]) for connector_id in ids]


def get_spec(connector_id: str) -> ConnectorSpec:
    try:
        return CATALOG[connector_id]
    except KeyError as exc:
        raise ContractError("unknown_connector") from exc


def get_fields(connector_id: str) -> dict[str, Any]:
    spec = get_spec(connector_id)
    return {
        "connector": connector_id,
        "fields": spec.fields,
        "implementation_status": spec.implementation_status,
        "available": spec.read_supported,
    }


def get_custom_fields(connector_id: str | None = None) -> dict[str, Any]:
    if connector_id in (None, "", "all"):
        items: list[dict[str, Any]] = []
        for item in CATALOG.values():
            if item.custom_fields and item.implementation_status == "implemented":
                for field in item.custom_fields:
                    items.append({"connector": item.connector_id, **field})
        return {"connector": None, "custom_fields": items, "implementation_status": "implemented_local"}
    spec = get_spec(connector_id)
    return {
        "connector": connector_id,
        "custom_fields": list(spec.custom_fields),
        "implementation_status": spec.implementation_status,
    }


def get_options(connector_id: str) -> dict[str, Any]:
    spec = get_spec(connector_id)
    dimensions = [key for key, value in spec.fields.items() if value["role"] == "dimension"]
    metrics = [key for key, value in spec.fields.items() if value["role"] == "metric"]
    return {
        "connector": connector_id,
        "available": spec.read_supported,
        "implementation_status": spec.implementation_status,
        "date_presets": ["all", "today", "yesterday", "last_7_days", "last_7d", "last_30_days", "last_30d", "last_90d", "last_year", "this_month", "last_month"],
        "date_filter_columns": ["date"],
        "breakdowns": dimensions,
        "metrics": metrics,
        "filter_operators": ["eq", "neq", "in", "contains", "ncontains", "gt", "gte", "lt", "lte", "null", "notnull"],
        "connector_options": ["date_preset", "date_from", "date_to", "select_accounts", "filters", "breakdowns", "refresh_since", "refresh_interval"],
        "renderers": ["json", "csv"],
        "account_ids": [account["id"] for account in spec.connected_accounts],
        "account_names": [account["name"] for account in spec.connected_accounts],
    }


def list_actions(connector_id: str) -> dict[str, Any]:
    spec = get_spec(connector_id)
    return {
        "connector": connector_id,
        "available": spec.write_supported,
        "implementation_status": spec.implementation_status,
        "writes_enabled": False,
        "actions": list(ACTION_SCHEMAS.get(connector_id, ())),
        "reason": "write adapters and explicit user authorization are required" if not spec.write_supported else None,
    }


def list_accounts(connector_id: str | None = None) -> dict[str, Any]:
    if connector_id in (None, "", "all"):
        accounts = []
        for spec in CATALOG.values():
            for account in spec.connected_accounts:
                accounts.append({"connector": spec.connector_id, **account, "status": "synthetic"})
        return {"connector": None, "accounts": accounts, "count": len(accounts), "mode": "local_synthetic_only"}
    spec = get_spec(connector_id)
    return {"connector": connector_id, "accounts": [{**account, "status": "synthetic"} for account in spec.connected_accounts], "count": len(spec.connected_accounts), "mode": "local_synthetic_only"}


def get_connect_info(connector_id: str) -> dict[str, Any]:
    spec = get_spec(connector_id)
    return {
        "connector": connector_id,
        "name": spec.name,
        "auth": spec.auth,
        "connection_status": "connected_synthetic" if spec.read_supported else "not_configured",
        "connected_accounts": spec.connected_accounts,
        "required_scopes": list(spec.scopes),
        "authorization_supported": connector_id in {"meta_ads", "facebook_pages", "instagram_business"},
        "authorization_endpoint": "/oauth/meta/start" if connector_id in {"meta_ads", "facebook_pages", "instagram_business"} else None,
        "write_status": "disabled_by_default",
        "reason": "provider_adapter_and_user_authorization_required" if not spec.read_supported else None,
    }


def _as_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ContractError(f"invalid_{key}")
    return [item.strip() for item in value]


def _as_filters(value: Any) -> Any:
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ContractError("invalid_filters") from exc
    if not isinstance(value, (dict, list)):
        raise ContractError("invalid_filters")
    return value


def _preset_range(preset: str, today: date) -> tuple[date | None, date | None]:
    if preset in ("", "all", "lifetime"):
        return None, None
    if preset == "today":
        return today, today
    if preset == "yesterday":
        value = today - timedelta(days=1)
        return value, value
    if preset in {"last_7_days", "last_7d"}:
        return today - timedelta(days=6), today
    if preset in {"last_30_days", "last_30d"}:
        return today - timedelta(days=29), today
    if preset == "last_90d":
        return today - timedelta(days=89), today
    if preset == "last_year":
        return today - timedelta(days=364), today
    if preset == "this_month":
        return today.replace(day=1), today
    if preset == "last_month":
        first = today.replace(day=1)
        last_previous = first - timedelta(days=1)
        return last_previous.replace(day=1), last_previous
    raise ContractError("invalid_date_preset")


def _date_range(options: dict[str, Any]) -> tuple[date | None, date | None, str]:
    preset = str(options.get("date_preset", "all") or "all")
    preset_start, preset_end = _preset_range(preset, date.today())
    raw_start = options.get("date_from")
    raw_end = options.get("date_to")
    try:
        start = date.fromisoformat(str(raw_start)) if raw_start else preset_start
        end = date.fromisoformat(str(raw_end)) if raw_end else preset_end
    except ValueError as exc:
        raise ContractError("invalid_date") from exc
    if start and end and start > end:
        raise ContractError("invalid_date_range")
    return start, end, preset


def _matches(value: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        operator = expected.get("operator", "eq")
        target = expected.get("value")
    else:
        operator = "eq"
        target = expected
    if operator == "eq":
        return value == target
    if operator == "neq":
        return value != target
    if operator == "in":
        return isinstance(target, list) and value in target
    if operator == "contains":
        return isinstance(value, str) and isinstance(target, str) and target.lower() in value.lower()
    if operator == "ncontains":
        return isinstance(value, str) and isinstance(target, str) and target.lower() not in value.lower()
    if operator in {"gt", "gte", "lt", "lte"}:
        try:
            if operator == "gt":
                return value > target
            if operator == "gte":
                return value >= target
            if operator == "lt":
                return value < target
            return value <= target
        except TypeError:
            return False
    if operator == "null":
        return value is None
    if operator == "notnull":
        return value is not None
    raise ContractError("invalid_filter_operator")


def _filter_fields(value: Any) -> set[str]:
    if isinstance(value, dict):
        if "field" in value:
            return {str(value["field"])}
        if "and" in value:
            return _filter_fields(value["and"])
        if "or" in value:
            return _filter_fields(value["or"])
        return {str(key) for key in value}
    if isinstance(value, list):
        if len(value) == 3 and isinstance(value[0], str) and isinstance(value[1], str):
            return {value[0]}
        return {field for item in value if not (isinstance(item, str) and item.lower() in {"and", "or"}) for field in _filter_fields(item)}
    return set()


def _matches_expression(row: dict[str, Any], expression: Any) -> bool:
    if expression in (None, {}, []):
        return True
    if isinstance(expression, dict):
        if "field" in expression:
            return _matches(row.get(str(expression.get("field"))), {"operator": expression.get("operation", expression.get("operator", "eq")), "value": expression.get("value")})
        if "and" in expression:
            items = expression["and"] if isinstance(expression["and"], list) else [expression["and"]]
            return all(_matches_expression(row, item) for item in items)
        if "or" in expression:
            items = expression["or"] if isinstance(expression["or"], list) else [expression["or"]]
            return any(_matches_expression(row, item) for item in items)
        return all(_matches(row.get(field), expected) for field, expected in expression.items())
    if isinstance(expression, list):
        if len(expression) == 3 and isinstance(expression[0], str) and isinstance(expression[1], str):
            return _matches(row.get(expression[0]), {"operator": expression[1], "value": expression[2]})
        results: list[bool] = []
        operators: list[str] = []
        for item in expression:
            if isinstance(item, str) and item.lower() in {"and", "or"}:
                operators.append(item.lower())
            else:
                results.append(_matches_expression(row, item))
        if not results:
            return True
        result = results[0]
        for index, value in enumerate(results[1:]):
            operator = operators[index] if index < len(operators) else "and"
            result = result and value if operator == "and" else result or value
        return result
    raise ContractError("invalid_filters")


def _derived(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    spend = float(result.get("spend") or 0)
    impressions = float(result.get("impressions") or 0)
    clicks = float(result.get("clicks") or 0)
    conversions = float(result.get("conversions") or 0)
    revenue = float(result.get("revenue") or 0)
    result["ctr"] = round(clicks / impressions * 100, 6) if impressions else 0
    result["cpc"] = round(spend / clicks, 6) if clicks else 0
    result["cpa"] = round(spend / conversions, 6) if conversions else 0
    result["roas"] = round(revenue / spend, 6) if spend else 0
    return result


def _aggregate(rows: list[dict[str, Any]], group_by: list[str], requested_fields: list[str]) -> list[dict[str, Any]]:
    if not group_by:
        return rows
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(field) for field in group_by)
        target = groups.setdefault(key, {field: row.get(field) for field in group_by})
        target["_count"] = target.get("_count", 0) + 1
        for field in requested_fields:
            if field in group_by:
                continue
            field_meta = COMMON_FIELDS.get(field, {})
            if field_meta.get("role") == "metric":
                target[field] = float(target.get(field, 0) or 0) + float(row.get(field) or 0)
            elif field not in target:
                target[field] = row.get(field)
    return [dict(row) for row in groups.values()]


def query_data(connector_id: str, fields: list[str], options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = dict(options or {})
    spec = get_spec(connector_id)
    if not spec.read_supported:
        raise ContractError("connector_not_available")
    fields = _as_list(fields, "fields")
    if not fields:
        raise ContractError("fields_required")
    unknown = sorted(set(fields) - set(spec.fields))
    if unknown:
        raise ContractError("invalid_fields:" + ",".join(unknown))
    group_by = _as_list(options.get("group_by", options.get("breakdowns")), "group_by")
    if any(field not in spec.fields for field in group_by):
        raise ContractError("invalid_group_by")
    select_accounts = _as_list(options.get("select_accounts"), "select_accounts")
    start, end, preset = _date_range(options)
    filters = _as_filters(options.get("filters", options.get("filter")))
    for field in _filter_fields(filters):
        if field not in spec.fields:
            raise ContractError("invalid_filter_field")
    rows: list[dict[str, Any]] = []
    for source_row in spec.rows:
        row = _derived(source_row)
        row_date = date.fromisoformat(row["date"])
        if start and row_date < start:
            continue
        if end and row_date > end:
            continue
        account_id = str(row.get("account_id") or "")
        account_candidates = {account_id}
        if connector_id == "all":
            account_candidates.update({f"{row.get('source')}__{account_id}", f"{row.get('source')}__act_{account_id}"})
        if select_accounts and not account_candidates.intersection(select_accounts):
            continue
        if not _matches_expression(row, filters):
            continue
        rows.append(row)
    requested_fields = list(dict.fromkeys(group_by + fields))
    rows = _aggregate(rows, group_by, requested_fields)
    rows = [{field: row.get(field) for field in requested_fields} for row in rows]
    try:
        page_size = int(options.get("page_size", options.get("_max_rows", 100)))
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid_page_size") from exc
    if page_size < 1 or page_size > 1000:
        raise ContractError("invalid_page_size")
    raw_cursor = options.get("cursor", "")
    try:
        offset = int(raw_cursor or 0)
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid_cursor") from exc
    if offset < 0:
        raise ContractError("invalid_cursor")
    page = rows[offset : offset + page_size]
    next_cursor = str(offset + page_size) if offset + page_size < len(rows) else None
    return {
        "connector": connector_id,
        "fields": requested_fields,
        "rows": page,
        "count": len(page),
        "total_count": len(rows),
        "next_cursor": next_cursor,
        "query": {
            "date_preset": preset,
            "date_from": start.isoformat() if start else None,
            "date_to": end.isoformat() if end else None,
            "select_accounts": select_accounts,
            "filters": filters,
            "group_by": group_by,
            "page_size": page_size,
            "refresh_since": options.get("refresh_since"),
            "refresh_interval": options.get("refresh_interval"),
            "cursor": str(offset) if offset else None,
        },
        "provenance": {
            "mode": "synthetic" if connector_id in ACTIVE_CONNECTORS else "provider",
            "connector": connector_id,
            "generated_at": date.today().isoformat(),
            "write_status": "disabled",
        },
    }


def to_csv(result: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=result["fields"], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(result["rows"])
    return output.getvalue()


def capability_matrix() -> dict[str, Any]:
    return {
        "contract_version": "0.4",
        "capabilities": [
            {"id": "connector_discovery", "status": "implemented", "evidence": "bridge_catalog.py:list_connectors"},
            {"id": "account_discovery_contract", "status": "implemented", "evidence": "connector metadata and get_connect_info"},
            {"id": "field_and_option_discovery", "status": "implemented", "evidence": "get_fields/get_options/get_custom_fields"},
            {"id": "blended_cross_channel_query", "status": "implemented_synthetic", "evidence": "all connector with provenance"},
            {"id": "date_presets_filters_breakdowns", "status": "implemented", "evidence": "query_data with nested filters and Windsor operator aliases"},
            {"id": "pagination", "status": "implemented", "evidence": "opaque numeric cursor contract"},
            {"id": "csv_export", "status": "implemented_local", "evidence": "to_csv"},
            {"id": "action_discovery", "status": "implemented_contract", "evidence": "list_actions with connector JSON schemas"},
            {"id": "destination_discovery", "status": "implemented_contract", "evidence": "get_destinations/get_destination_setup_info"},
            {"id": "custom_field_contract", "status": "implemented_contract_only", "evidence": "get_custom_fields/create_custom_field validation"},
            {"id": "provider_oauth", "status": "partial", "evidence": "Meta state/PKCE flow; provider secrets and live account auth remain external"},
            {"id": "social_publishing", "status": "contract_only_blocked", "evidence": "preview_action; no adapter or live account"},
            {"id": "paid_campaign_writes", "status": "contract_only_blocked", "evidence": "preview_action; writes disabled"},
            {"id": "destinations_and_sync", "status": "not_implemented", "evidence": "requires destination adapters and persistence"},
            {"id": "multi_tenant_public_auth", "status": "not_implemented", "evidence": "local single-user bridge only"},
        ],
        "provider_catalog_count": len(WINDSOR_CONNECTOR_IDS),
        "bridge_catalog_count_with_aliases": len(CATALOG),
        "catalog_source": WINDSOR_DATASOURCE_URL,
        "active_local_connectors": list(ACTIVE_CONNECTORS),
        "writes_enabled": False,
        "unlimited_claim": False,
        "unlimited_reason": "External provider quotas, rate limits, scopes and terms still apply.",
    }

