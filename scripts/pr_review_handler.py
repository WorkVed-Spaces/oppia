import os
import json
from github import Github, GithubException

def sanitize_username(username):
    """Sanitize GitHub username to prevent injection attacks"""
    return ''.join(c for c in username if c.isalnum() or c in ['-', '_'])

def handle_approval(g, repo, pr, author):
    """Handle approved review scenario"""
    try:
        # Get all requested reviewers
        pr_obj = repo.get_pull(pr.number)
        requested_reviewers = [r.login for r in pr_obj.get_review_requests()[0]]
        
        # Get all approvals
        reviews = pr_obj.get_reviews()
        approvals = {review.user.login for review in reviews if review.state == 'APPROVED'}
        
        # Check pending reviewers
        pending_reviewers = [r for r in requested_reviewers if r not in approvals]
        
        if not pending_reviewers:
            # Add LGTM label
            pr.add_to_labels('LGTM')
            
            # Assign author
            pr.add_to_assignees(author)
            print(f"Assigned {author} to PR #{pr.number}")
        else:
            # Re-request reviews
            pr.create_review_request(reviewers=pending_reviewers)
            print(f"Re-requested reviews from {', '.join(pending_reviewers)}")
            
    except GithubException as e:
        print(f"Error handling approval: {e}")
        raise

def handle_changes_requested(repo, pr, author, reviewer):
    """Handle changes requested scenario"""
    try:
        # Remove LGTM label if exists
        try:
            pr.remove_from_labels('LGTM')
        except GithubException as e:
            if e.status != 404:
                raise
        
        # Unassign reviewer
        pr.remove_from_assignees(reviewer)
        
        # Assign author
        pr.add_to_assignees(author)
        print(f"Unassigned {reviewer} and assigned {author} to PR #{pr.number}")
        
    except GithubException as e:
        print(f"Error handling changes requested: {e}")
        raise

def main():
    # Get inputs
    token = os.getenv('GITHUB_TOKEN')
    event_path = os.getenv('GITHUB_EVENT_PATH')
    
    with open(event_path) as f:
        event_data = json.load(f)
    
    review = event_data['review']
    pr_data = event_data['pull_request']
    repo_name = os.getenv('GITHUB_REPOSITORY')
    
    # Sanitize inputs
    author = sanitize_username(pr_data['user']['login'])
    reviewer = sanitize_username(review['user']['login'])
    review_state = review['state'].lower()
    
    # Initialize GitHub objects
    g = Github(token)
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_data['number'])
    
    if review_state == 'approved':
        handle_approval(g, repo, pr, author)
    elif review_state == 'changes_requested':
        handle_changes_requested(repo, pr, author, reviewer)
    else:
        print(f"Ignoring review state: {review_state}")

if __name__ == "__main__":
    main()
