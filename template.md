<a href="{github_url}" target="_blank"><img alt="Github" src="https://img.shields.io/badge/GitHub-%2312100E.svg?&style=for-the-badge&logo=Github&logoColor=white" /></a> &nbsp;&nbsp; <a href="{linkedin_url}" target="_blank"><img alt="LinkedIn" src="https://img.shields.io/badge/linkedin-%230077B5.svg?&style=for-the-badge&logo=linkedin&logoColor=white" /></a> &nbsp;&nbsp; <img alt="Github" src="https://img.shields.io/badge/Last%20Updated-{last_updated}-brightgreen" height='28'/>

<table>
  <tr>
    <td>
      <h3>Issues ({issue_count})</h3>
      <ul><issues><li><a href='{issue_url}'>{issue_title}</a> {updated_at}</li></issues></ul>
      <h3>Pull Requests ({pr_count})</h3>
      <ul><prs><li><a href='{pr_url}'>{pr_title}</a> {updated_at}</li></prs></ul>
      <h3>Recent Acivity</h3>
      <ul><recent><li><a href='{recent_activity_url}'>{recent_activity_title}</a></li></recent></ul>
      <h3>Gists</h3>
      <ul><gists><li><a href='{gist_url}'>{gist_title}</a></li></gists></ul>
    </td>
    <td>
      <h3>Work related stuff over on</h3>
      <ul><orgs><li><a href='{org_url}'>{org_name}</a></li></orgs></ul>
      <br/><img alt="Redhat" width='200px' src="https://github.com/dmzoneill/dmzoneill/blob/main/images/redhat.svg?raw=true" />      
    </td>
  </tr>
</table>

<h3>Lines of code</h3>    
<table>
  <thead>
    <tr>
      <th>Language</th>
      <th>Lines</th>
      <th>Language</th>
      <th>Lines</th>
      <th>Language</th>
      <th>Lines</th>
      <th>Language</th>
      <th>Lines</th>
    </tr>
  </thead>
  <tbody>
    <tr><langs><td>{language}</td><td>{lines}</td></langs></tr>
  </tbody>
</table>

### Some things i've been poking at

<table width='100%' style='width:100%'>
  <thead>
    <tr>
      <th>Project</th>
      <th>View</th>
      <th>Status</th>
    </tr>
  </thead>
  <tbody>
    <repos>
        <tr>
            <td>
              <p><a href='{html_url}' title='{name}'>{name}</a> {first_commit}</p><p>{language}</p>
              <p>{license}</p>
              <p><ul><recent><li><a href='{recent_activity_url}'>{recent_activity_title}</a></li></recent></ul></p>
              <p><ul><issues><li><a href='{issue_url}'>{issue_title}</a> {updated_at}</li></issues></ul></p>
              <p><ul><prs><li><a href='{pr_url}'>{pr_title}</a> {updated_at}</li></prs></ul></p>
            </td>
            <td>
              <p><a href='{live_url}' title='{live_name}'>{live_name}</a></p>
            </td>
            <td align="center">
              <a href='https://github.com/dmzoneill/{name}/actions'><img src='{badge}'/></a>
              <p>{updated_at}</p>
            </td>
        </tr>
    </repos>
  </tbody>
</table>
