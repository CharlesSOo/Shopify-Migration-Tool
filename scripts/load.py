#scripts/load.py

import requests
import os
import time
import json
from dotenv import load_dotenv

load_dotenv()

# Shopify API Configuration
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_PASSWORD = os.getenv("SHOPIFY_ADMIN_API_ACCESS_TOKEN") or os.getenv("SHOPIFY_PASSWORD")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
API_VERSION = "2024-01"

# Progress tracking
PROGRESS_FILE = "data/upload_progress.json"

def save_completed_order(woo_order_id):
    """Save completed order ID to progress file"""
    os.makedirs('data', exist_ok=True)
    
    completed_orders = load_completed_orders()
    if woo_order_id not in completed_orders:
        completed_orders.append(woo_order_id)
        
        with open(PROGRESS_FILE, 'w') as f:
            json.dump({
                'completed_orders': completed_orders,
                'last_updated': time.time()
            }, f)

def load_completed_orders():
    """Load list of completed order IDs"""
    if not os.path.exists(PROGRESS_FILE):
        return []
    
    try:
        with open(PROGRESS_FILE, 'r') as f:
            data = json.load(f)
            return data.get('completed_orders', [])
    except:
        return []

def clear_progress():
    """Clear progress file for fresh start"""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        print("✅ Progress file cleared")

def check_rate_limit_and_wait(response_headers):
    """Check Shopify rate limit headers and wait if necessary"""
    rate_limit_header = response_headers.get('X-Shopify-Shop-Api-Call-Limit', '0/40')
    
    try:
        current, max_limit = map(int, rate_limit_header.split('/'))
        usage_percent = (current / max_limit) * 100
        
        # Dynamic waiting based on bucket usage
        if current >= 35:  # 87.5% full - slow down significantly
            wait_time = 2.0
            print(f"🐌 Rate limit high ({current}/{max_limit}) - waiting {wait_time}s")
        elif current >= 30:  # 75% full - moderate slowdown
            wait_time = 1.0
            print(f"⚡ Rate limit moderate ({current}/{max_limit}) - waiting {wait_time}s")
        elif current >= 20:  # 50% full - slight slowdown
            wait_time = 0.5
        else:  # Plenty of capacity - minimal wait
            wait_time = 0.1
            
        time.sleep(wait_time)
        return current, max_limit
        
    except (ValueError, AttributeError):
        # Fallback if header parsing fails
        time.sleep(0.5)
        return 0, 40

def upload_to_shopify(endpoint, data, max_retries=3, max_retry_cycles=5):
    """Upload data to Shopify API with intelligent rate limiting and retries"""
    url = f"https://{SHOPIFY_API_KEY}:{SHOPIFY_PASSWORD}@{SHOPIFY_STORE}/admin/api/{API_VERSION}/{endpoint}.json"
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # Debug: Print JSON payload for first few orders
    if data.get('woo_order_id', 0) <= 3:
        payload = {endpoint[:-1]: data}
        print(f"🔍 DEBUG JSON Payload for Order {data.get('woo_order_id')}:")
        print(f"   processed_at: {data.get('processed_at')}")
        print(f"   financial_status: {data.get('financial_status')}")
        print(f"   created_at: {data.get('created_at')}")
    
    for cycle in range(max_retry_cycles):
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    url,
                    json={endpoint[:-1]: data},  # 'products' → 'product'
                    headers=headers,
                    timeout=15
                )
                
                # Handle rate limiting (429) specifically
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 5))
                    print(f"🚫 Rate limited! Waiting {retry_after}s as instructed by Shopify...")
                    time.sleep(retry_after)
                    continue  # Retry this attempt
                
                # Check rate limit headers for future requests
                if response.status_code == 200:
                    check_rate_limit_and_wait(response.headers)
                
                # Handle other errors
                if response.status_code >= 400:
                    error_msg = f"API Error {response.status_code}"
                    try:
                        error_details = response.json()
                        error_msg += f": {error_details.get('errors', 'Unknown error')}"
                        
                        # Extra debugging for processed_at errors
                        if 'processed_at' in str(error_details):
                            print(f"🔍 PROCESSED_AT DEBUG:")
                            print(f"   Order ID: {data.get('woo_order_id')}")
                            print(f"   processed_at value: '{data.get('processed_at')}'")
                            print(f"   processed_at type: {type(data.get('processed_at'))}")
                            print(f"   financial_status: {data.get('financial_status')}")
                            print(f"   created_at: {data.get('created_at')}")
                            
                    except:
                        error_msg += f": {response.text}"
                    print(error_msg)
                    response.raise_for_status()
                    
                return response.json()
                
            except requests.exceptions.RequestException as e:
                print(f"⚠️ Cycle {cycle + 1}, Attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    print(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                else:
                    # All attempts in this cycle failed
                    if cycle < max_retry_cycles - 1:
                        print(f"🔄 All {max_retries} attempts failed. Waiting 10s before starting new retry cycle...")
                        time.sleep(10)
                        break  # Break from attempt loop to start new cycle
                    else:
                        print(f"❌ All retry cycles exhausted for {data.get('id', 'unknown')}")
                        raise

def batch_upload(endpoint, items, batch_size=5, resume_mode=False):
    """Upload items in batches with progress tracking"""
    successes = 0
    total_items = len(items)
    
    # Resume functionality for orders
    completed_orders = []
    if endpoint == "orders" and resume_mode:
        completed_orders = load_completed_orders()
        print(f"📂 Found {len(completed_orders)} completed orders, will skip these")
    
    print(f"\nStarting {endpoint} upload ({total_items} items)...")
    
    for i in range(0, total_items, batch_size):
        batch = items[i:i + batch_size]
        for item in batch:
            try:
                # Skip if already completed (resume mode)
                if endpoint == "orders" and item.get('woo_order_id') in completed_orders:
                    print(f"⏭️  Skipping completed order #{item.get('woo_order_id')}")
                    successes += 1
                    continue
                
                print(f"Processing {endpoint[:-1]} {successes+1}/{total_items}...")
                
                # Special handling for customers
                if endpoint == "customers":
                    if not item.get("email"):
                        print("❌ Skipping customer - missing email")
                        continue
                
                result = upload_to_shopify(endpoint, item)
                
                # Save progress for orders
                if endpoint == "orders" and item.get('woo_order_id'):
                    save_completed_order(item.get('woo_order_id'))
                    print(f"  ✅ Progress saved: Order #{item.get('woo_order_id')}")

                successes += 1
                
                # Progress update every 100 orders (no prompts, just info)
                if successes > 0 and successes % 100 == 0:
                    remaining = total_items - successes
                    print(f"\n📊 PROGRESS: {successes:,}/{total_items:,} uploaded ({(successes/total_items)*100:.1f}%) - {remaining:,} remaining")
                
                # Rate limiting is now handled automatically in upload_to_shopify()
                # No need for additional delays here
                
            except Exception as e:
                print(f"❌ Failed to upload {endpoint[:-1]} {item.get('id', 'unknown')}: {str(e)}")
                continue
    
    print(f"✅ Uploaded {successes}/{total_items} {endpoint}")
    return successes

def format_phone_e164(phone):
    """Format phone number to E.164 format (+1XXXXXXXXXX)"""
    if not phone:
        return None
    
    # Remove all non-digits
    import re
    digits_only = re.sub(r'[^\d]', '', str(phone))
    
    # Handle different formats
    if len(digits_only) == 10:
        # US/Canada number without country code
        return f"+1{digits_only}"
    elif len(digits_only) == 11 and digits_only.startswith('1'):
        # US/Canada number with country code
        return f"+{digits_only}"
    elif len(digits_only) >= 10:
        # International number, assume it already has country code
        return f"+{digits_only}"
    else:
        # Invalid phone number
        return None

def create_dummy_test_orders(orders, test_count=10):
    """Create dummy test orders to avoid emailing real customers"""
    import copy
    import random
    from datetime import datetime, timedelta
    
    if len(orders) < test_count:
        test_count = len(orders)
    
    # Define test email addresses to cycle through
    test_emails = [
        "charles@linkinguplocal.com",
        "m@charles.so", 
        "charlesterzich@gmail.com",
        "trevor@trevorfosterstudio.com"
    ]
    
    # Define random date ranges for backdating orders
    date_ranges = [
        timedelta(weeks=2),    # 2 weeks ago
        timedelta(weeks=5),    # 5 weeks ago
        timedelta(weeks=12),   # 3 months ago
        timedelta(weeks=26),   # 6 months ago
        timedelta(days=365),   # 1 year ago
        timedelta(days=730),   # 2 years ago
        timedelta(days=1095),  # 3 years ago
    ]
    
    dummy_orders = []
    
    for i in range(test_count):
        # Make a deep copy of the order
        dummy_order = copy.deepcopy(orders[i])
        
        # Replace email with test email (cycle through the list)
        dummy_order['email'] = test_emails[i % len(test_emails)]
        
        # Always keep original dates from WooCommerce
        print(f"  📅 Using original date: {dummy_order.get('created_at', 'Unknown')}")
        
        # Keep fulfillment date same as order date
        if dummy_order.get('fulfillment_status') == 'fulfilled':
            order_date = dummy_order.get('created_at', '')
            print(f"    🚚 Fulfilled on same date: {order_date[:10] if order_date else 'Unknown'}")
        
        # Update billing address and customer phone
        if dummy_order.get('billing_address'):
            dummy_order['billing_address']['first_name'] = "Test"
            dummy_order['billing_address']['last_name'] = f"Customer{i+1}"
            dummy_order['billing_address']['phone'] = format_phone_e164(dummy_order['billing_address'].get('phone'))
        
        # Format customer-level phone
        if dummy_order.get('phone'):
            dummy_order['phone'] = format_phone_e164(dummy_order['phone'])
        
        # Update shipping address
        if dummy_order.get('shipping_address'):
            dummy_order['shipping_address']['first_name'] = "Test"
            dummy_order['shipping_address']['last_name'] = f"Customer{i+1}"
        
        # Add test identifier to order
        dummy_order['note'] = f"TEST ORDER {i+1} - Original WooCommerce Order #{dummy_order.get('woo_order_id')}"
        
        dummy_orders.append(dummy_order)
    
    return dummy_orders

def fix_order_data_for_shopify(order):
    """Fix common data issues that cause Shopify API validation errors"""
    
    # Skip voided orders entirely - no need to migrate cancelled/failed orders
    if order.get('financial_status') == 'voided':
        print(f"⏭️  Skipping voided order #{order.get('woo_order_id')} - not migrating cancelled orders")
        return None
    
    # Debug: Print order details for first few orders
    if order.get('woo_order_id', 0) <= 5:
        print(f"🔍 DEBUG Order {order.get('woo_order_id')}:")
        print(f"   financial_status: {order.get('financial_status')}")
        print(f"   processed_at (before): {order.get('processed_at')}")
        print(f"   created_at: {order.get('created_at')}")
    
    # Fix processed_at field - required when financial_status is 'paid'
    if order.get('financial_status') == 'paid':
        if not order.get('processed_at'):
            # Use created_at as processed_at if date_paid is missing
            order['processed_at'] = order.get('created_at')
            if order.get('woo_order_id', 0) <= 5:
                print(f"   ✅ Set processed_at to created_at: {order['processed_at']}")
        elif order.get('processed_at'):
            # Ensure date format is correct (sometimes it's null string)
            if order['processed_at'] in [None, '', 'null']:
                order['processed_at'] = order.get('created_at')
                if order.get('woo_order_id', 0) <= 5:
                    print(f"   ✅ Fixed null processed_at: {order['processed_at']}")
    else:
        # COMPLETELY REMOVE processed_at if order is not paid (Shopify doesn't allow it)
        if 'processed_at' in order:
            del order['processed_at']
            if order.get('woo_order_id', 0) <= 5:
                print(f"   ✅ REMOVED processed_at field for non-paid order")
    
    # Ensure required fields are not None
    if not order.get('email'):
        print(f"⚠️  Warning: Order {order.get('woo_order_id')} missing email - skipping")
        return None
        
    return order

def load_woocommerce_orders(test_mode=False, test_count=10):
    """Load WooCommerce orders from the exported JSON file"""
    
    # Check both possible locations for the file
    possible_files = [
        'data/shopify_orders_ready.json',           # Expected location
        'scripts/data/shopify_orders_ready.json'    # Current location
    ]
    
    orders_file = None
    for file_path in possible_files:
        if os.path.exists(file_path):
            orders_file = file_path
            break
    
    if not orders_file:
        print("❌ WooCommerce orders file not found in any expected location:")
        for path in possible_files:
            print(f"   - {path}")
        print("   Run: python scripts/woocommerce_order_exporter.py first")
        return []
    
    try:
        with open(orders_file, 'r') as f:
            orders = json.load(f)
        
        # Fix data issues before processing
        fixed_orders = []
        for order in orders:
            fixed_order = fix_order_data_for_shopify(order)
            if fixed_order:  # Only add orders that pass validation
                fixed_orders.append(fixed_order)
        
        orders = fixed_orders
        
        if test_mode:
            # Create dummy test orders instead of using real ones
            orders = create_dummy_test_orders(orders, test_count)
            print(f"🧪 TEST MODE: Created {len(orders)} dummy orders for testing (with original dates)")
            print(f"   📧 Test orders will cycle through 4 different test emails")
        else:
            # Fix phone numbers and set fulfillment dates for all real orders
            for order in orders:
                # Format customer-level phone
                if order.get('phone'):
                    order['phone'] = format_phone_e164(order['phone'])
                # Format address phones
                if order.get('billing_address', {}).get('phone'):
                    order['billing_address']['phone'] = format_phone_e164(order['billing_address']['phone'])
                if order.get('shipping_address', {}).get('phone'):
                    order['shipping_address']['phone'] = format_phone_e164(order['shipping_address']['phone'])
                
                # Keep fulfillment date same as order date for real orders too
                # (Shopify will use the order creation date as fulfillment date when status is 'fulfilled')
            
            print(f"✅ Loaded {len(orders)} orders from WooCommerce export (with original dates)")
        
        return orders
    except FileNotFoundError:
        print("❌ WooCommerce orders file not found. Run woocommerce_order_exporter.py first.")
        return []
    except Exception as e:
        print(f"❌ Error loading WooCommerce orders: {str(e)}")
        return []

def test_upload():
    """Test upload with 10 orders"""
    print("🧪 TESTING SHOPIFY UPLOAD")
    print("="*50)
    print("Testing with 10 orders first...")
    
    orders = load_woocommerce_orders(test_mode=True, test_count=10)
    if not orders:
        return False
    
    print(f"\n📋 Test orders preview:")
    for i, order in enumerate(orders[:3], 1):
        created_date = order.get('created_at', '')[:10] if order.get('created_at') else 'Unknown'
        print(f"  {i}. Order #{order.get('woo_order_id')} - {order.get('email')} - ${order.get('total_price')} - {created_date}")
    if len(orders) > 3:
        print(f"  ... and {len(orders)-3} more orders (with original dates)")
    
    # Confirm test upload
    response = input(f"\n🚀 Upload these {len(orders)} test orders to Shopify? (y/n): ").lower().strip()
    if response != 'y':
        print("❌ Test upload cancelled")
        return False
    
    # Upload test orders
    successes = batch_upload("orders", orders, batch_size=3)  # Smaller batches for testing
    
    if successes == len(orders):
        print(f"\n✅ TEST SUCCESSFUL! All {successes} orders uploaded successfully")
        return True
    else:
        print(f"\n⚠️  TEST ISSUES: Only {successes}/{len(orders)} orders uploaded successfully")
        return False

def full_upload(resume_mode=False):
    """Upload all orders with optional resume capability"""
    action = "Resuming" if resume_mode else "Starting"
    print(f"\n🚀 {action.upper()} FULL SHOPIFY UPLOAD")
    print("="*50)
    
    orders = load_woocommerce_orders(test_mode=False)
    if not orders:
        return
    
    if resume_mode:
        completed_orders = load_completed_orders()
        remaining = len(orders) - len(completed_orders)
        print(f"📊 Resume summary:")
        print(f"   - Total orders: {len(orders):,}")
        print(f"   - Completed: {len(completed_orders):,}")
        print(f"   - Remaining: {remaining:,}")
    else:
        print(f"📊 Full upload summary:")
        print(f"   - Total orders: {len(orders):,}")
    
    # Show status breakdown
    status_counts = {}
    for order in orders:
        status = order.get('financial_status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print(f"   - Financial statuses: {status_counts}")
    
    # Estimate time
    if resume_mode:
        remaining_orders = len(orders) - len(load_completed_orders())
        estimated_minutes = (remaining_orders * 3.5) / 60
    else:
        estimated_minutes = (len(orders) * 3.5) / 60
    print(f"   - Estimated time: {estimated_minutes:.1f} minutes")
    
    # Final confirmation
    action_text = "RESUME upload of remaining" if resume_mode else "Upload ALL"
    order_count = len(orders) - len(load_completed_orders()) if resume_mode else len(orders)
    response = input(f"\n🚀 {action_text} {order_count:,} orders to Shopify? (y/n): ").lower().strip()
    if response != 'y':
        print(f"❌ {action} cancelled")
        return
    
    # Upload all orders
    successes = batch_upload("orders", orders, batch_size=5, resume_mode=resume_mode)
    
    print(f"\n{'✅' if successes == len(orders) else '⚠️'} UPLOAD COMPLETE!")
    print(f"Successfully uploaded: {successes:,}/{len(orders):,} orders")
    
    if successes < len(orders):
        print(f"⚠️  {len(orders) - successes} orders failed - check logs above for details")

if __name__ == "__main__":
    print("🚀 Shopify Upload Tool")
    print("="*50)
    
    # Check if we have WooCommerce order data
    possible_files = [
        'data/shopify_orders_ready.json',
        'scripts/data/shopify_orders_ready.json'
    ]
    
    orders_file_exists = any(os.path.exists(f) for f in possible_files)
    if not orders_file_exists:
        print("❌ No WooCommerce order export found")
        print("   Checked:")
        for path in possible_files:
            print(f"   - {path}")
        print("   Run: python scripts/woocommerce_order_exporter.py first")
        exit(1)
    
    print("📦 Found WooCommerce orders export")
    
    # Check for existing progress
    completed_orders = load_completed_orders()
    if completed_orders:
        print(f"📂 Found existing progress: {len(completed_orders)} orders already uploaded")
    
    # Get user choice
    print("\nChoose upload mode:")
    print("1. 🧪 Test upload (10 orders)")
    print("2. 🚀 Full upload (all orders)")
    if completed_orders:
        print("3. 🔄 Resume upload (continue from where you left off)")
        print("4. 🗑️  Clear progress and start fresh")
        print("5. ❌ Exit")
        choice_range = "(1/2/3/4/5)"
    else:
        print("3. ❌ Exit")
        choice_range = "(1/2/3)"
    
    choice = input(f"\nEnter your choice {choice_range}: ").strip()
    
    if choice == "1":
        # Test upload first (always using original dates)
        test_success = test_upload()
        
        if test_success:
            # Ask if they want to continue with full upload
            response = input("\n🎉 Test successful! Continue with full upload? (y/n): ").lower().strip()
            if response == 'y':
                full_upload()
            else:
                print("✅ Test complete. Run script again when ready for full upload.")
        else:
            print("❌ Test failed. Please fix issues before proceeding.")
            
    elif choice == "2":
        # Go straight to full upload
        if completed_orders:
            response = input("⚠️  You have existing progress. Start fresh or resume? (fresh/resume): ").lower().strip()
            if response == 'resume':
                full_upload(resume_mode=True)
            elif response == 'fresh':
                clear_progress()
                full_upload(resume_mode=False)
            else:
                print("💡 Choose 'fresh' or 'resume'")
        else:
            response = input("⚠️  Skip testing and upload all orders directly? (y/n): ").lower().strip()
            if response == 'y':
                full_upload()
            else:
                print("💡 Consider running test upload first (option 1)")
    
    elif choice == "3" and completed_orders:
        # Resume upload
        full_upload(resume_mode=True)
        
    elif choice == "4" and completed_orders:
        # Clear progress
        clear_progress()
        print("🔄 Run script again to start fresh upload")
        
    elif choice == "5" and completed_orders or choice == "3" and not completed_orders:
        print("👋 Goodbye!")
        
    else:
        max_choice = 5 if completed_orders else 3
        print(f"❌ Invalid choice. Please run again and select 1-{max_choice}.")